"""Participant workflow orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from rich import box
from rich.table import Table

from mrsiprep.interfaces.freesurfer import freesurfer_subject_id, subject_dir_valid
from mrsiprep.io.bids import BIDSLayout, Recording
from mrsiprep.io.derivatives import init_derivative
from mrsiprep.io.loaders import load_mrsi_inputs
from mrsiprep.io.validators import ValidationError, validate_recording
from mrsiprep.mrsi.pvc import create_tissue_4d, run_pvc
from mrsiprep.utils.debug import Debug
from mrsiprep.mrsi.resampling import transform_mrsi_maps
from mrsiprep.parcellation.extraction import extract_regional_metabolites
from mrsiprep.parcellation.tissue_regression import regional_tissue_regression
from mrsiprep.parcellation.metprofiles import export_metprofile_npz
from mrsiprep.parcellation.synthseg import run_synthseg_parcellation
from mrsiprep.reports.parcel_qc import write_parcel_qc
from mrsiprep.reports.parcel_figures import write_parcel_qc_figures
from mrsiprep.reports.qc_combine import combine_qc_reports
from mrsiprep.reports.connectivity_overview import write_connectivity_qc_report
from mrsiprep.reports.mrsi_preproc import write_mrsi_preproc_qc_report
from mrsiprep.reports.parcellation_overview import write_parcellation_qc_report
from mrsiprep.reports.registration_overview import write_registration_overview_report
from mrsiprep.tissue.synthseg_fast import (
    extract_t1_synthseg,
    segment_t1_synthseg_fast,
    synthseg_fast_brain_path,
    synthseg_fast_brain_mask_path,
    synthseg_fast_csf_probseg_path,
)
from mrsiprep.utils.images import resolve_mni_resolution
from mrsiprep.utils.misc import format_elapsed_hm, normalize_session, normalize_subject, read_participant_pairs
from mrsiprep.workflows.anatomical import prepare_anatomical
from mrsiprep.workflows.base import ensure_work_dirs
from mrsiprep.workflows.connectivity import run_connectivity_workflow
from mrsiprep.workflows.mrsi import run_mrsi_workflow
from mrsiprep.workflows.parcellation import run_parcellation_workflow
from mrsiprep.workflows.registration import run_registration_workflow
from mrsiprep.workflows.reports import run_reports_workflow
from mrsiprep.workflows.tissue import run_tissue_workflow, segment_t1_fuzzy_cmeans


@dataclass
class RecordingStatus:
    subject: str
    session: str | None
    status: str
    outputs: dict = field(default_factory=dict)
    error: str | None = None


def _gather_input_availability(config, subject: str, session: str | None) -> dict:
    from mrsiprep.utils.images import nifti_validity_error

    layout = BIDSLayout(config.bids_dir, filters=config.bids_filters)
    recording_id = f"sub-{subject}"
    if session:
        recording_id += f"_ses-{session}"

    check_integrity = not config.skip_file_integrity_check

    t1_path = layout.t1(subject, session, config.t1_pattern)
    t1_status = bool(t1_path and t1_path.exists())
    t1_corrupt = bool(t1_status and check_integrity and nifti_validity_error(t1_path))

    inputs = load_mrsi_inputs(layout, subject, session, config.metabolites)
    total_expected = len(config.metabolites)
    found_count = len(inputs.metabolite_maps)
    crlb_found_count = len(inputs.crlb_maps)
    snr_status = bool(inputs.snr_map)
    fwhm_status = bool(inputs.linewidth_map)

    corrupt_items = []
    if check_integrity:
        if t1_corrupt:
            corrupt_items.append("T1w")
        for met, path in inputs.metabolite_maps.items():
            if nifti_validity_error(path):
                corrupt_items.append(f"MRSI-{met}")
        for met, path in inputs.crlb_maps.items():
            if nifti_validity_error(path):
                corrupt_items.append(f"CRLB-{met}")
        if inputs.snr_map is not None and nifti_validity_error(inputs.snr_map):
            corrupt_items.append("SNR")
        if inputs.linewidth_map is not None and nifti_validity_error(inputs.linewidth_map):
            corrupt_items.append("FWHM")

    brainmask_status = bool(inputs.brainmask)
    if config.tissue_backend == "existing":
        tissue_statuses = [
            bool(layout.cat12_probseg(subject, session, idx))
            for idx in (1, 2, 3)
        ]
        tissue_label = " ".join(
            f"[{'green' if status else 'red'}]p{idx}[/{'green' if status else 'red'}]"
            for idx, status in enumerate(tissue_statuses, 1)
        )
    else:
        tissue_label = "[cyan]AUTO[/cyan]"

    transform_stages = ["mrsi", "anat"]
    if config.longitudinal:
        transform_stages.append("t1-template")
    transforms = {}
    for stage in transform_stages:
        stage_paths = layout.transform(subject, session, stage)
        transforms[stage] = bool(stage_paths and all(path.exists() for path in stage_paths))

    freesurfer_status: bool | None = None
    if config.processing_mode == "parc-con" and config.parcellation_mode == "chimera":
        raw_t1 = layout.raw_t1(subject, session)
        if raw_t1 is not None:
            fs_subject = freesurfer_subject_id(raw_t1)
            freesurfer_status = subject_dir_valid(config.freesurfer_dir, fs_subject)
        else:
            freesurfer_status = False

    return {
        "recording_id": recording_id,
        "subject": subject,
        "session": session,
        "t1": t1_status,
        "mrsi_found": found_count,
        "mrsi_expected": total_expected,
        "crlb_found": crlb_found_count,
        "snr": snr_status,
        "fwhm": fwhm_status,
        "brainmask": brainmask_status,
        "tissue": tissue_label,
        "transforms": transforms,
        "freesurfer": freesurfer_status,
        "corrupt_items": corrupt_items,
    }


def _render_preflight_table(config, summaries: list[dict], debug: Debug) -> None:
    CHECK_MARK = "[green]✔[/green]"
    CROSS_MARK = "[red]X[/red]"
    PROC_MARK = "[orange3]PROC[/orange3]"
    NA_MARK = "[grey58]N/A[/grey58]"
    transform_columns = [
        ("mrsi", "MRSI→T1"),
        ("anat", "T1→MNI"),
    ]
    if config.longitudinal:
        transform_columns.append(("t1-template", "Ses→Template"))

    show_freesurfer = any(row["freesurfer"] is not None for row in summaries)

    show_integrity = not config.skip_file_integrity_check

    table = Table(box=box.SIMPLE_HEAVY, show_lines=False, title="Input availability summary")
    table.add_column("Recording", style="cyan", no_wrap=True)
    table.add_column("T1w ref", justify="center", no_wrap=True)
    table.add_column("MRSI files", justify="center", no_wrap=True)
    table.add_column("CRLB", justify="center", no_wrap=True)
    table.add_column("SNR", justify="center", no_wrap=True)
    table.add_column("FWHM", justify="center", no_wrap=True)
    table.add_column("Brainmask", justify="center", no_wrap=True)
    table.add_column("Tissue files", justify="center", no_wrap=True)
    if show_integrity:
        table.add_column("Integrity", justify="center", no_wrap=True)
    if show_freesurfer:
        table.add_column("FreeSurfer", justify="center", no_wrap=True)
    for _, label in transform_columns:
        table.add_column(label, justify="center", no_wrap=True)

    missing_count = 0
    total_missing_files = 0
    missing_recordings = []
    subject_session_counts: dict[str, int] = {}
    for row in summaries:
        subject_session_counts[row["subject"]] = subject_session_counts.get(row["subject"], 0) + (1 if row["session"] else 1)

    for row in summaries:
        mrsi_color = "green" if row["mrsi_found"] == row["mrsi_expected"] else "red"
        mrsi_cell = f"[{mrsi_color}]{row['mrsi_found']}/{row['mrsi_expected']}[/{mrsi_color}]"
        crlb_color = "green" if row["crlb_found"] == row["mrsi_expected"] else "red"
        crlb_cell = f"[{crlb_color}]{row['crlb_found']}/{row['mrsi_expected']}[/{crlb_color}]"
        t1_cell = CHECK_MARK if row["t1"] else CROSS_MARK
        snr_cell = CHECK_MARK if row["snr"] else CROSS_MARK
        fwhm_cell = CHECK_MARK if row["fwhm"] else CROSS_MARK
        brainmask_cell = CHECK_MARK if row["brainmask"] else PROC_MARK

        row_cells = [
            row["recording_id"],
            t1_cell,
            mrsi_cell,
            crlb_cell,
            snr_cell,
            fwhm_cell,
            brainmask_cell,
            row["tissue"],
        ]

        if show_integrity:
            corrupt_items = row.get("corrupt_items") or []
            if corrupt_items:
                row_cells.append(f"[red]CORRUPT ({', '.join(corrupt_items)})[/red]")
            else:
                row_cells.append(CHECK_MARK)

        if show_freesurfer:
            if row["freesurfer"] is None:
                row_cells.append(NA_MARK)
            else:
                row_cells.append(CHECK_MARK if row["freesurfer"] else PROC_MARK)

        for stage_key, _ in transform_columns:
            row_cells.append(CHECK_MARK if row["transforms"].get(stage_key, False) else PROC_MARK)

        table.add_row(*row_cells)

        missing_items = []
        if not row["t1"]:
            missing_items.append("T1w")
        if row["mrsi_found"] != row["mrsi_expected"]:
            missing_items.append(f"MRSI {row['mrsi_found']}/{row['mrsi_expected']}")
        if "crlb" in config.quality_metrics and row["crlb_found"] != row["mrsi_expected"]:
            missing_items.append(f"CRLB {row['crlb_found']}/{row['mrsi_expected']}")
        if "snr" in config.quality_metrics and not row["snr"]:
            missing_items.append("SNR")
        if "linewidth" in config.quality_metrics and not row["fwhm"]:
            missing_items.append("FWHM")
        if config.processing_mode == "parc-con" and config.tissue_backend == "existing" and "red" in row["tissue"]:
            missing_items.append("Tissue")
        if row.get("corrupt_items"):
            missing_items.append(f"CORRUPT ({', '.join(row['corrupt_items'])})")

        if missing_items:
            missing_count += 1
            total_missing_files += len(missing_items)
            missing_recordings.append(row["recording_id"])

    debug.separator()
    debug.title("Preflight input availability")
    debug.console.print(table)
    if missing_count:
        debug.error(
            f"Detected {total_missing_files} missing or incomplete file categories across {missing_count}/{len(summaries)} recordings. "
            f"Affected recordings: {', '.join(missing_recordings)}"
        )
    else:
        debug.success("All required inputs are available for the selected recordings.")

    nproc, nthreads, cpu_warning = config.resolve_cpu_budget()
    if cpu_warning:
        debug.always(f"[warning]WARNING:[/warning] {cpu_warning}")
    else:
        debug.always(f"CPU budget: --nproc {nproc} x --nthreads {nthreads} = {nproc * nthreads} threads (of {os.cpu_count()} available).")


def collect_recordings(config) -> list[Recording]:
    if config.participants_file:
        return [Recording(sub, ses) for sub, ses in read_participant_pairs(config.participants_file)]
    subjects = config.participant_label or []
    sessions = config.session_label or []
    if subjects:
        if sessions:
            return [Recording(normalize_subject(sub), normalize_session(ses)) for sub in subjects for ses in sessions]
        return [Recording(normalize_subject(sub), None) for sub in subjects]
    return BIDSLayout(config.bids_dir, filters=config.bids_filters).discover_recordings()


def _format_elapsed(seconds: float) -> str:
    return format_elapsed_hm(seconds)


def _build_subject_templates(config, ready: list[Recording], debug: Debug) -> dict[str, object]:
    """Build one subject-level template per subject with >=2 ready sessions.

    Runs once, before per-recording dispatch, so every recording's Nipype
    workflow can be seeded with its subject's precomputed template (see
    ``build_recording_workflow``'s ``subject_template`` param). Subjects with
    a single ready session are absent from the returned dict; their
    recordings fall back to direct per-session T1-to-MNI registration.
    """
    from mrsiprep.io.bids import BIDSLayout
    from mrsiprep.registration.subject_template import build_subject_template

    by_subject: dict[str, list[str]] = {}
    for recording in ready:
        if recording.session:
            by_subject.setdefault(recording.subject, []).append(recording.session)

    templates: dict[str, object] = {}
    layout = BIDSLayout(config.bids_dir, filters=config.bids_filters)
    for subject, sessions in by_subject.items():
        if len(sessions) < 2:
            continue
        with debug.step(f"Building subject template (sub-{subject}, {len(sessions)} sessions)"):
            session_t1_paths = {}
            for session in sessions:
                t1_path, _inputs = validate_recording(config, subject, session)
                raw_t1 = layout.raw_t1(subject, session)
                _, precomputed_tissue_t1, p3_override, brain_mask_override = _step_tissue_segmentation(
                    config, subject, session, raw_t1, t1_path, debug
                )
                anat = _step_anatomical_prep(config, subject, session, t1_path, p3_override, brain_mask_override, debug)
                session_t1_paths[session] = anat.registration_t1w
            templates[subject] = build_subject_template(config, subject, session_t1_paths)
    return templates


def run_participant_workflow(config) -> list[RecordingStatus]:
    ensure_work_dirs(config)
    init_derivative(config.derivative_dir)
    debug = Debug(verbose=config.verbose)

    recordings = collect_recordings(config)
    if recordings:
        summaries = [
            _gather_input_availability(config, normalize_subject(rec.subject), normalize_session(rec.session))
            for rec in recordings
        ]
        _render_preflight_table(config, summaries, debug)

    ready: list[Recording] = []
    statuses: list[RecordingStatus] = []
    for recording in recordings:
        subject = normalize_subject(recording.subject)
        session = normalize_session(recording.session)
        try:
            validate_recording(config, subject, session)
            _validate_backend_inputs(config, subject, session)
            ready.append(Recording(subject, session))
        except (ValidationError, FileNotFoundError) as exc:
            msg = f"sub-{subject}" + (f" ses-{session}" if session else "")
            debug.error("SKIP", msg, str(exc))
            statuses.append(RecordingStatus(subject, session, "skipped", error=str(exc)))

    if not ready:
        return statuses

    subject_templates: dict[str, object] = {}
    if config.longitudinal:
        subject_templates = _build_subject_templates(config, ready, debug)

    from mrsiprep.workflows.nipype_engine.run import execute_recordings_nipype

    statuses.extend(execute_recordings_nipype(config, ready, subject_templates=subject_templates))
    return statuses


def validate_participant_inputs(config) -> list[RecordingStatus]:
    debug = Debug(verbose=config.verbose)
    recordings = collect_recordings(config)
    summaries = [
        _gather_input_availability(config, normalize_subject(rec.subject), normalize_session(rec.session))
        for rec in recordings
    ]
    _render_preflight_table(config, summaries, debug)

    statuses: list[RecordingStatus] = []
    for recording in recordings:
        subject = normalize_subject(recording.subject)
        session = normalize_session(recording.session)
        try:
            t1_path, inputs = validate_recording(config, subject, session)
            _validate_backend_inputs(config, subject, session)
            outputs = {
                "t1w": t1_path,
                "metabolites": sorted(inputs.metabolite_maps),
                "snr": inputs.snr_map,
                "linewidth": inputs.linewidth_map,
                "brainmask": inputs.brainmask,
            }
            statuses.append(RecordingStatus(subject, session, "success", outputs=outputs))
        except Exception as exc:
            statuses.append(RecordingStatus(subject, session, "failed", error=str(exc)))
            debug.error("INVALID", f"sub-{subject}", f"ses-{session}" if session else "", str(exc))
    return statuses


def _validate_backend_inputs(config, subject: str, session: str | None) -> None:
    layout = BIDSLayout(config.bids_dir, filters=config.bids_filters)
    raw_t1 = layout.raw_t1(subject, session)
    if config.processing_mode == "mni-norm" and raw_t1 is None:
        raise FileNotFoundError(f"Missing raw T1w required for light-mode SynthSeg parcellation: sub-{subject} ses-{session}")
    if config.tissue_backend == "synthseg-fast" and raw_t1 is None:
        raise FileNotFoundError(f"Missing raw T1w required for {config.tissue_backend}: sub-{subject} ses-{session}")
    if config.parcellation_mode == "mni" and config.atlas == "custom":
        if not config.custom_atlas or not config.custom_atlas.exists():
            raise FileNotFoundError("--custom-atlas is required for --parcellation-mode mni --atlas custom")
        if not config.custom_atlas_lut or not config.custom_atlas_lut.exists():
            raise FileNotFoundError("--custom-atlas-lut is required for --parcellation-mode mni --atlas custom")


def _step_tissue_segmentation(config, subject, session, raw_t1, t1_path, debug):
    """Light mode: SynthSeg brain extraction. Full+synthseg-fast: SynthSeg+FAST inputs.

    Returns (t1_path, precomputed_tissue_t1, p3_override, brain_mask_override),
    where t1_path may be overridden from the input value.
    """
    precomputed_tissue_t1 = None
    p3_override = None
    brain_mask_override = None
    with debug.step("Tissue segmentation"):
        if config.processing_mode == "mni-norm":
            if raw_t1 is None:
                raise FileNotFoundError(f"Missing raw T1w required for SynthSeg+FAST segmentation: sub-{subject} ses-{session}")
            precomputed_tissue_t1 = segment_t1_synthseg_fast(config, subject, session, raw_t1)
            p3_override = synthseg_fast_csf_probseg_path(config, subject, session)
            if config.registration_t1_target == "brain":
                t1_path = synthseg_fast_brain_path(config, subject, session)
                brain_mask_override = synthseg_fast_brain_mask_path(config, subject, session)
        elif config.processing_mode == "midas":
            if raw_t1 is None:
                raise FileNotFoundError(f"Missing raw T1w required for MIDAS fuzzy c-means segmentation: sub-{subject} ses-{session}")
            synthseg_brain, synthseg_mask = extract_t1_synthseg(config, subject, session, raw_t1)
            precomputed_tissue_t1 = segment_t1_fuzzy_cmeans(config, subject, session, synthseg_brain, synthseg_mask)
            t1_path = synthseg_brain
            brain_mask_override = synthseg_mask
            p3_override = precomputed_tissue_t1["CSF"]
        elif config.processing_mode == "parc-con" and config.tissue_backend == "synthseg-fast":
            if raw_t1 is None:
                raise FileNotFoundError(f"Missing raw T1w required for SynthSeg+FAST segmentation: sub-{subject} ses-{session}")
            precomputed_tissue_t1 = segment_t1_synthseg_fast(config, subject, session, raw_t1)
            t1_path = synthseg_fast_brain_path(config, subject, session)
            brain_mask_override = synthseg_fast_brain_mask_path(config, subject, session)
            p3_override = synthseg_fast_csf_probseg_path(config, subject, session)
    return t1_path, precomputed_tissue_t1, p3_override, brain_mask_override


def _step_anatomical_prep(config, subject, session, t1_path, p3_override, brain_mask_override, debug):
    with debug.step("Anatomical preparation"):
        return prepare_anatomical(config, subject, session, t1_path, p3_override=p3_override, brain_mask_override=brain_mask_override)


def _step_mrsi_preprocessing(config, subject, session, inputs, debug):
    with debug.step("MRSI preprocessing"):
        mrsi = run_mrsi_workflow(config, subject, session, inputs)
        qc_report_mrsi_preproc = write_mrsi_preproc_qc_report(config, subject, session, mrsi.raw_maps, mrsi.preproc_maps)
    return mrsi, qc_report_mrsi_preproc


def _step_registration(config, subject, session, mrsi, anat, debug, subject_template=None):
    with debug.step("MRSI-T1w-MNI registration"):
        return run_registration_workflow(
            config,
            subject,
            session,
            mrsi.reference,
            anat.registration_t1w,
            anat.registration_mask,
            mrsi_mask=mrsi.brainmask,
            subject_template=subject_template,
        )


def _step_tissue_probmaps(config, subject, session, anat, mrsi, registration, precomputed_tissue_t1, debug):
    if config.processing_mode not in {"parc-con", "midas", "mni-norm"}:
        return None
    with debug.step("Tissue probability maps in MRSI space"):
        return run_tissue_workflow(
            config,
            subject,
            session,
            anat.registration_t1w,
            anat.registration_mask,
            mrsi.reference,
            registration.mrsi_to_t1.inverse,
            precomputed_tissue_t1=precomputed_tissue_t1,
        )


def _step_pvc(config, subject, session, mrsi, tissue, debug):
    """Returns (corrected_maps, tissue_4d). corrected_maps defaults to
    mrsi.preproc_maps unchanged when full-mode PVC is not applicable."""
    corrected_maps = mrsi.preproc_maps
    tissue_4d = None
    if config.processing_mode in {"parc-con", "mni-norm"} and not config.no_pvc:
        assert tissue is not None
        with debug.step("Partial volume correction"):
            tissue_4d = create_tissue_4d(config, subject, session, tissue.mrsi, mrsi.reference)
            corrected_maps = run_pvc(config, subject, session, mrsi.preproc_maps, tissue_4d, mrsi.brainmask)
            mrsi.corrected_maps = corrected_maps
    return corrected_maps, tissue_4d


def _step_resampling(config, subject, session, anat, mrsi, registration, corrected_maps, raw_t1, debug):
    with debug.step("Resampling MRSI maps to T1w/MNI space"):
        transformed = transform_mrsi_maps(
            config,
            subject,
            session,
            corrected_maps,
            registration.mrsi_to_t1.forward,
            registration.t1_to_mni.forward if registration.t1_to_mni else None,
            anat.registration_t1w,
            mrsi_reference=mrsi.reference,
            crlb_maps=mrsi.crlb_maps,
            snr_map=mrsi.snr_map,
            linewidth_map=mrsi.linewidth_map,
        )
        mni_resolution = resolve_mni_resolution(config.mni_resolution, anat.registration_t1w, mrsi.reference) if registration.t1_to_mni else None
        qc_report_registration = write_registration_overview_report(
            config,
            subject,
            session,
            raw_t1,
            transformed.get("T1w", {}).get(config.ref_met),
            transformed.get("MNI152NLin2009cAsym", {}).get(config.ref_met),
            mni_resolution=mni_resolution,
            orig_ref_map_path=corrected_maps.get(config.ref_met),
            mrsi_to_t1_transforms=registration.mrsi_to_t1.forward,
        )
    return transformed, qc_report_registration


def _step_synthseg_parcellation_qc(config, subject, session, raw_t1, mrsi, registration, debug):
    with debug.step("SynthSeg parcellation and QC"):
        preliminary_parcels = run_synthseg_parcellation(
            config,
            subject,
            session,
            raw_t1,
            mrsi.reference,
            registration.mrsi_to_t1.inverse,
        )
        parcel_qc = write_parcel_qc(
            config,
            subject,
            session,
            preliminary_parcels,
            raw_t1,
            mrsi.brainmask,
            registration.mrsi_to_t1.forward,
            mrsi.crlb_maps,
            mrsi.qcmasks,
        )
        write_parcel_qc_figures(
            config,
            subject,
            session,
            preliminary_parcels.atlas_t1,
            parcel_qc,
            t1_to_mni=registration.t1_to_mni.forward if registration.t1_to_mni else None,
        )
    return preliminary_parcels, parcel_qc


def _step_parcellation(config, subject, session, raw_t1, mrsi, anat, registration, preliminary_parcels, debug):
    """Returns (parcels, qc_report_parcellation). parcels defaults to the
    preliminary SynthSeg parcellation outside parc-con mode."""
    parcels = preliminary_parcels
    qc_report_parcellation = None
    if config.processing_mode in {"parc-con", "midas"}:
        with debug.step("Parcellation"):
            parcels = run_parcellation_workflow(
                config,
                subject,
                session,
                mrsi.reference,
                registration,
                raw_t1=raw_t1,
                t1_reference=anat.registration_t1w,
            )
            qc_report_parcellation = write_parcellation_qc_report(config, subject, session, raw_t1, parcels.atlas_t1, parcels.labels)
    return parcels, qc_report_parcellation


def _step_regional_extraction(config, subject, session, corrected_maps, parcels, mrsi, tissue, debug):
    """Returns (regional_table, regional_regression). regional_regression is the
    MIDAS Eq. 4-5 pure-GM/pure-WM regression TSV in ``midas`` mode, else None."""
    with debug.step("Regional metabolite extraction"):
        regional = extract_regional_metabolites(
            config,
            subject,
            session,
            corrected_maps,
            parcels,
            mrsi.qcmasks,
            mrsi.snr_map,
            mrsi.linewidth_map,
            mrsi.crlb_maps,
            tissue.mrsi if tissue is not None else {},
        )
        regional_regression = None
        if config.processing_mode == "midas" and tissue is not None:
            regional_regression = regional_tissue_regression(
                config, subject, session, corrected_maps, parcels, mrsi.qcmasks, tissue.mrsi
            )
    return regional, regional_regression


def _step_connectivity(config, subject, session, regional, parcels, corrected_maps, mrsi, tissue, debug):
    with debug.step("Connectivity", live=False):
        connectivity = run_connectivity_workflow(
            config,
            subject,
            session,
            regional,
            parcels,
            corrected_maps,
            mrsi.crlb_maps,
            mrsi.brainmask,
            gm_fraction_path=tissue.mrsi.get("GM") if tissue is not None else None,
        )
        qc_report_connectivity = write_connectivity_qc_report(config, subject, session, connectivity.get("matrix_tsv"))
    return connectivity, qc_report_connectivity


def _step_metprofiles(config, subject, session, corrected_maps, mrsi, parcels, regional, anat):
    if config.processing_mode not in {"parc-con", "midas"}:
        return None
    return export_metprofile_npz(
        config,
        subject,
        session,
        corrected_maps,
        mrsi.water_map,
        parcels,
        regional,
        anat.registration_mask,
    )


def _step_reports(config, subject, session, outputs, debug):
    with debug.step("Reports"):
        report = run_reports_workflow(config, subject, session, outputs)
        outputs["report"] = report
        outputs["qc_report_combined"] = combine_qc_reports(config, subject, session)
        for key in ("qc_report_tissue", "qc_report_mrsi_preproc", "qc_report_registration", "qc_report_parcellation", "qc_report_connectivity"):
            outputs.pop(key, None)
    return outputs

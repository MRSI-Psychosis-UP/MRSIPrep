"""The individual pipeline stages.

Each ``_step_*`` function is one stage of the per-recording pipeline: it takes
the config plus whatever previous stages produced, does one thing, and returns
its outputs. They are deliberately plain functions rather than classes so they
can be called directly (as :mod:`mrsiprep.workflows.participant` does) or
wrapped as graph nodes (as :mod:`mrsiprep.workflows.nipype_engine.nodes`
does). The canonical execution order is ``STEP_SEQUENCE`` in that nodes module.

Ordering and orchestration live in :mod:`mrsiprep.workflows.participant`;
the pre-run inventory lives in :mod:`mrsiprep.workflows.preflight`.
"""

from __future__ import annotations

from mrsiprep.io.bids import BIDSLayout
from mrsiprep.mrsi.pvc import create_tissue_4d, run_pvc
from mrsiprep.mrsi.resampling import transform_mrsi_maps
from mrsiprep.parcellation.extraction import extract_regional_metabolites
from mrsiprep.parcellation.metprofiles import export_metprofile_npz
from mrsiprep.parcellation.synthseg import run_synthseg_parcellation
from mrsiprep.reports.connectivity_overview import build_connectivity_qc_sections
from mrsiprep.reports.leakage_qc import write_signal_leakage_qc
from mrsiprep.reports.mrsi_preproc import build_mrsi_preproc_qc_sections
from mrsiprep.reports.mrsi_raw_overview import build_mrsi_raw_qc_sections
from mrsiprep.reports.parcel_figures import write_parcel_qc_figures
from mrsiprep.reports.parcel_qc import write_parcel_qc
from mrsiprep.reports.parcellation_overview import build_parcellation_qc_sections
from mrsiprep.reports.registration_overview import build_mni_alignment_sections, build_t1w_alignment_sections
from mrsiprep.reports.t1_correction import build_t1_correction_qc_sections
from mrsiprep.qc.ventricles import ventricle_reference_mask
from mrsiprep.reports.ventricle_overview import build_ventricle_qc_sections
from mrsiprep.tissue.synthseg_fast import (
    segment_t1_synthseg_fast,
    synthseg_fast_brain_mask_path,
    synthseg_fast_brain_path,
    synthseg_fast_csf_probseg_path,
)
from mrsiprep.workflows.anatomical import prepare_anatomical
from mrsiprep.workflows.connectivity import run_connectivity_workflow
from mrsiprep.workflows.mrsi import (
    run_mrsi_load_workflow,
    run_mrsi_quality_workflow,
    run_mrsi_reference_workflow,
    run_spike_filter_workflow,
    run_t1_saturation_correction_workflow,
)
from mrsiprep.workflows.parcellation import run_parcellation_workflow
from mrsiprep.workflows.registration import run_registration_workflow
from mrsiprep.workflows.reports import run_reports_workflow
from mrsiprep.workflows.tissue import run_tissue_workflow

def _validate_backend_inputs(config, subject: str, session: str | None) -> None:
    layout = BIDSLayout.from_config(config)
    raw_t1 = layout.raw_t1(subject, session)
    if config.tissue_backend == "synthseg-fast" and raw_t1 is None:
        raise FileNotFoundError(f"Missing raw T1w required for {config.tissue_backend}: sub-{subject} ses-{session}")
    if config.parcellation_mode == "atlas" and config.atlas == "custom":
        if not config.custom_atlas or not config.custom_atlas.exists():
            raise FileNotFoundError("--custom-atlas is required for --parcellation-mode atlas --atlas custom")
        if not config.custom_atlas_lut or not config.custom_atlas_lut.exists():
            raise FileNotFoundError("--custom-atlas-lut is required for --parcellation-mode atlas --atlas custom")


def _step_tissue_segmentation(config, subject, session, raw_t1, t1_path, debug):
    """Runs SynthSeg+FAST when --tissue-backend synthseg-fast (the default);
    a no-op otherwise ('existing' reuses CAT12 p1/p2/p3 maps found directly
    on disk, 'none' skips tissue segmentation and PVC entirely).

    Returns (t1_path, precomputed_tissue_t1, p3_override, brain_mask_override),
    where t1_path may be overridden from the input value.
    """
    precomputed_tissue_t1 = None
    p3_override = None
    brain_mask_override = None
    with debug.step("Tissue segmentation"):
        if config.tissue_backend == "synthseg-fast":
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


def _step_mrsi_load(config, subject, session, inputs, debug, anat=None):
    with debug.step("MRSI loading"):
        t1_path = anat.registration_t1w if anat is not None else None
        load = run_mrsi_load_workflow(config, subject, session, inputs, t1_path=t1_path)
    return load


def _step_spike_filter(config, subject, session, load, debug):
    with debug.step("Spike filtering"):
        filtered = run_spike_filter_workflow(config, subject, session, load)
        qc_sections_mrsi_raw = build_mrsi_raw_qc_sections(config, subject, session, load.raw_maps, filtered.preproc_maps)
        qc_sections_mrsi_preproc = build_mrsi_preproc_qc_sections(config, subject, session, load.raw_maps, filtered.preproc_maps)
    return filtered, qc_sections_mrsi_raw, qc_sections_mrsi_preproc


def _step_t1_saturation_correction(config, subject, session, load, filtered, debug):
    with debug.step("T1 saturation correction"):
        water = run_t1_saturation_correction_workflow(config, subject, session, load, filtered)
        qc_sections_t1_correction = None
        if water.provenance is not None:
            qc_sections_t1_correction = build_t1_correction_qc_sections(
                config, subject, session, filtered.preproc_maps, water.corrected_maps, water.provenance
            )
    return water, qc_sections_t1_correction


def _step_mrsi_reference(config, subject, session, load, filtered, water, inputs, debug):
    with debug.step("MRSI reference image"):
        # The ventricle section is appended at the reports step
        # (_step_ventricle_qc), once the MRSI->T1w transform exists to score it.
        return run_mrsi_reference_workflow(config, subject, session, load, filtered, water, inputs)


def _step_mrsi_quality(config, subject, session, water, inputs, brainmask, debug):
    with debug.step("MRSI voxel-quality masks"):
        return run_mrsi_quality_workflow(config, subject, session, water, inputs, brainmask)


def _step_ventricle_qc(config, subject, session, raw_t1, mrsi_reference, registration):
    """Ventricle visibility section for the MRSI Raw tab.

    Detection itself uses no coregistration; it runs here, after
    registration, only so each metabolite's detection can also be scored
    against the subject's own SynthSeg lateral ventricles moved into MRSI
    space. Without SynthSeg labels or a transform the section still renders,
    just without the Dice chart.
    """
    reference = None
    mrsi_to_t1 = getattr(registration, "mrsi_to_t1", None)
    if mrsi_to_t1 is not None:
        reference = ventricle_reference_mask(config, subject, session, raw_t1, mrsi_reference.reference, mrsi_to_t1.inverse)
    return build_ventricle_qc_sections(config, subject, session, mrsi_reference.raw_maps, reference_ventricles=reference)


def _step_registration(config, subject, session, mrsi_reference, anat, debug, subject_template=None):
    # No debug.step() here: the workflow reports its two registrations
    # separately, since they are independent and very differently priced.
    return run_registration_workflow(
        config,
        subject,
        session,
        mrsi_reference.reference,
        anat.registration_t1w,
        anat.registration_mask,
        mrsi_mask=mrsi_reference.brainmask,
        subject_template=subject_template,
        debug=debug,
    )


def _step_tissue_probmaps(config, subject, session, anat, mrsi_reference, registration, precomputed_tissue_t1, debug):
    with debug.step("Tissue probability maps in MRSI space"):
        return run_tissue_workflow(
            config,
            subject,
            session,
            anat.registration_t1w,
            anat.registration_mask,
            mrsi_reference.reference,
            registration.mrsi_to_t1.inverse,
            precomputed_tissue_t1=precomputed_tissue_t1,
        )


def _step_pvc(config, subject, session, mrsi_reference, tissue, debug):
    """Returns (corrected_maps, tissue_4d). corrected_maps defaults to
    mrsi_reference.preproc_maps unchanged when --no-pvc is set."""
    corrected_maps = mrsi_reference.preproc_maps
    tissue_4d = None
    if not config.no_pvc:
        if tissue is None:
            raise ValueError("PVC requires tissue segmentation, but none was provided")
        with debug.step("Partial volume correction"):
            tissue_4d = create_tissue_4d(config, subject, session, tissue.mrsi, mrsi_reference.reference)
            corrected_maps = run_pvc(
                config, subject, session, mrsi_reference.preproc_maps, tissue_4d, mrsi_reference.brainmask, mrsi_reference.reference
            )
    return corrected_maps, tissue_4d


def _step_resampling(config, subject, session, anat, mrsi_reference, registration, corrected_maps, raw_t1, debug):
    with debug.step("Resampling MRSI maps to T1w/MNI space"):
        transformed = transform_mrsi_maps(
            config,
            subject,
            session,
            corrected_maps,
            registration.mrsi_to_t1.forward,
            registration.t1_to_mni.forward if registration.t1_to_mni else None,
            anat.registration_t1w,
            mrsi_reference=mrsi_reference.reference,
            crlb_maps=mrsi_reference.crlb_maps,
            snr_map=mrsi_reference.snr_map,
            linewidth_map=mrsi_reference.linewidth_map,
        )
        mni_resolution = (
            config.resolution_for("MNI152NLin2009cAsym", anat.registration_t1w, mrsi_reference.reference)
            if registration.t1_to_mni
            else None
        )
        qc_sections_t1w_alignment = build_t1w_alignment_sections(
            config,
            subject,
            session,
            raw_t1,
            transformed.get("T1w", {}).get(config.ref_met),
            orig_ref_map_path=corrected_maps.get(config.ref_met),
            mrsi_to_t1_transforms=registration.mrsi_to_t1.forward,
            t1_maps=transformed.get("T1w"),
        )
        qc_sections_mni_alignment = build_mni_alignment_sections(
            config,
            subject,
            session,
            transformed.get("MNI152NLin2009cAsym", {}).get(config.ref_met),
            mni_resolution=mni_resolution,
            t1_to_mni_transforms=registration.t1_to_mni.forward if registration.t1_to_mni else None,
            mni_maps=transformed.get("MNI152NLin2009cAsym"),
        )
    return transformed, qc_sections_t1w_alignment, qc_sections_mni_alignment


def _step_leakage_qc(config, subject, session, anat, transformed, debug):
    """Per-metabolite signal-weighted leakage outside the reference brain
    mask, in whichever resampled space(s) were produced -- the same
    metric used to compare registration backends (docs/benchmarks.md).
    Returns None if no resampled space has a reference brain mask
    available (e.g. neither MNI output nor T1w output with a T1w
    reference brain mask, as with ``--registration-t1-target raw``)."""
    with debug.step("Signal leakage QC"):
        return write_signal_leakage_qc(config, subject, session, transformed, anat.registration_mask)


def _step_synthseg_parcellation_qc(config, subject, session, raw_t1, mrsi_reference, mrsi_quality, registration, debug, transformed=None):
    with debug.step("SynthSeg parcellation and QC"):
        preliminary_parcels = run_synthseg_parcellation(
            config,
            subject,
            session,
            raw_t1,
            mrsi_reference.reference,
            registration.mrsi_to_t1.inverse,
        )
        parcel_qc = write_parcel_qc(
            config,
            subject,
            session,
            preliminary_parcels,
            mrsi_reference.brainmask,
            mrsi_reference.crlb_maps,
            mrsi_quality.qcmasks,
        )
        # MNI152NLin2009cAsym-space CRLB maps, already written by the
        # resampling step that ran earlier in STEP_SEQUENCE -- reused rather
        # than resampled a second time here. `crlb-{met}` is the key
        # _resample_space's _quality_items() names them under.
        mni_outputs = (transformed or {}).get("MNI152NLin2009cAsym", {})
        mni_crlb_maps = {
            met: path
            for key, path in mni_outputs.items()
            if key.startswith("crlb-") and (met := key[len("crlb-") :]) in mrsi_reference.crlb_maps
        }
        write_parcel_qc_figures(
            config,
            subject,
            session,
            preliminary_parcels.atlas_t1,
            parcel_qc,
            atlas_mrsi=preliminary_parcels.atlas_mrsi,
            t1_to_mni=registration.t1_to_mni.forward if registration.t1_to_mni else None,
            mrsi_reference=mrsi_reference.reference,
            crlb_maps=mni_crlb_maps or None,
        )
    return preliminary_parcels, parcel_qc


def _step_parcellation(config, subject, session, raw_t1, mrsi_reference, anat, registration, preliminary_parcels, debug):
    """Returns (parcels_list, qc_sections_parcellation).

    Always a list: synthseg mode contributes the preliminary SynthSeg
    parcellation as its single entry, while chimera/atlas modes contribute one
    entry per comma-separated scheme/scale/atlas requested. QC sections for
    every parcellation are concatenated into one Parcellation tab, each headed
    by its parcellation id.
    """
    if config.parcellation_mode == "synthseg":
        return [preliminary_parcels], None
    with debug.step("Parcellation"):
        parcels_list = run_parcellation_workflow(
            config,
            subject,
            session,
            mrsi_reference.reference,
            registration,
            raw_t1=raw_t1,
            t1_reference=anat.registration_t1w,
        )
        qc_sections_parcellation = []
        multiple = len(parcels_list) > 1
        for parcels in parcels_list:
            sections = build_parcellation_qc_sections(config, subject, session, raw_t1, parcels.atlas_t1, parcels.labels)
            if multiple:
                sections = [(f"{parcels.parcellation_id}: {heading}", body) for heading, body in sections]
            qc_sections_parcellation.extend(sections)
    return parcels_list, qc_sections_parcellation


def _step_regional_extraction(config, subject, session, corrected_maps, parcels_list, mrsi_reference, mrsi_quality, tissue, debug):
    """Returns {parcellation_id: regional_table_path}, one entry per parcellation."""
    regional = {}
    for parcels in parcels_list:
        label = "Regional metabolite extraction"
        if len(parcels_list) > 1:
            label += f" ({parcels.parcellation_id})"
        with debug.step(label):
            regional[parcels.parcellation_id] = extract_regional_metabolites(
                config,
                subject,
                session,
                corrected_maps,
                parcels,
                mrsi_quality.qcmasks,
                mrsi_reference.snr_map,
                mrsi_reference.linewidth_map,
                mrsi_reference.crlb_maps,
                tissue.mrsi if tissue is not None else {},
            )
    return regional


def _step_connectivity(config, subject, session, regional, parcels_list, corrected_maps, mrsi_reference, tissue, debug):
    """Regional metabolic profile estimation (CRLB-scaled Monte Carlo
    uncertainty propagation) always runs, for every recording; the metabolic
    connectivity matrix is the optional add-on gated on
    ``--write-connectivity`` (see ``run_connectivity_workflow``).

    Runs once per parcellation, returning
    ``({parcellation_id: outputs}, qc_sections)``.

    Metabolites with no CRLB map (e.g. a dataset whose quantification
    pipeline never exported per-metabolite CRLB) still get a profile --
    ``compute_metabolic_profiles`` treats missing CRLB as 0% (no injected
    noise), so their "perturbed" draws are just the raw signal value; see
    that function's docstring for the ``n_perturbations`` degeneracy this
    implies when no metabolite has real CRLB at all.
    """
    connectivity = {}
    qc_sections_connectivity = []
    multiple = len(parcels_list) > 1
    for parcels in parcels_list:
        pid = parcels.parcellation_id
        label = "Regional metabolic profiles" + (" and connectivity" if config.write_connectivity else "")
        if multiple:
            label += f" ({pid})"
        with debug.step(label, live=False):
            connectivity[pid] = run_connectivity_workflow(
                config,
                subject,
                session,
                regional[pid],
                parcels,
                corrected_maps,
                mrsi_reference.crlb_maps,
                mrsi_reference.brainmask,
                gm_fraction_path=tissue.mrsi.get("GM") if tissue is not None else None,
            )
            sections = build_connectivity_qc_sections(config, subject, session, connectivity[pid].get("matrix_tsv"))
            if sections and multiple:
                sections = [(f"{pid}: {heading}", body) for heading, body in sections]
            if sections:
                qc_sections_connectivity.extend(sections)
    return connectivity, (qc_sections_connectivity or None)


def _step_metprofiles(config, subject, session, corrected_maps, mrsi_reference, parcels_list, regional, anat):
    """Returns {parcellation_id: metprofile_npz_path}, one entry per parcellation."""
    return {
        parcels.parcellation_id: export_metprofile_npz(
            config,
            subject,
            session,
            corrected_maps,
            mrsi_reference.water_map,
            parcels,
            regional[parcels.parcellation_id],
            anat.registration_mask,
        )
        for parcels in parcels_list
    }


def _step_reports(config, subject, session, outputs, qc_sections, debug):
    with debug.step("Reports"):
        report = run_reports_workflow(config, subject, session, outputs, qc_sections)
        outputs["report"] = report
    return outputs

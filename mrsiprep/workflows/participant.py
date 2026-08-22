"""Participant-level orchestration.

Resolves which recordings to process, runs the preflight inventory, then drives
each recording through the pipeline stages, collecting a per-recording
:class:`RecordingStatus`. This module owns *ordering and error handling*; the
stages themselves live in :mod:`mrsiprep.workflows.steps` and the pre-run
inventory in :mod:`mrsiprep.workflows.preflight`.

Those two modules were split out of this one purely to keep each readable --
this module re-exports their public names below, so
``from mrsiprep.workflows.participant import _step_registration`` and friends
keep working for existing callers (notably
:mod:`mrsiprep.workflows.nipype_engine.nodes`).
"""

from __future__ import annotations

import time
import traceback

from mrsiprep.io.bids import BIDSLayout, Recording
from mrsiprep.io.derivatives import init_derivative
from mrsiprep.io.validators import ValidationError, validate_recording
from mrsiprep.utils.debug import Debug
from mrsiprep.utils.misc import format_elapsed_hm, normalize_session, normalize_subject, read_participant_pairs
from mrsiprep.workflows.base import ensure_work_dirs

# Re-exported for backwards compatibility -- see the module docstring. These
# are intentionally unused here; importing them is the point.
# pylint: disable=unused-import
from mrsiprep.workflows.preflight import (  # noqa: F401
    _PREFLIGHT_CHECK_MARK,
    _PREFLIGHT_CROSS_MARK,
    _PREFLIGHT_NA_MARK,
    _PREFLIGHT_PROC_MARK,
    RecordingStatus,
    _build_preflight_table,
    _gather_input_availability,
    _preflight_corrupt_items,
    _preflight_freesurfer_status,
    _preflight_missing_items,
    _preflight_row_cells,
    _preflight_t1_status,
    _preflight_tissue_label,
    _preflight_transform_columns,
    _preflight_transform_status,
    _render_preflight_table,
    _report_cpu_budget,
    _report_preflight_summary,
)
from mrsiprep.workflows.steps import (  # noqa: F401
    _step_anatomical_prep,
    _step_connectivity,
    _step_leakage_qc,
    _step_metprofiles,
    _step_mrsi_preprocessing,
    _step_parcellation,
    _step_pvc,
    _step_registration,
    _step_regional_extraction,
    _step_reports,
    _step_resampling,
    _step_synthseg_parcellation_qc,
    _step_tissue_probmaps,
    _step_tissue_segmentation,
    _validate_backend_inputs,
)


def collect_recordings(config) -> list[Recording]:
    """Resolve the (subject, session) recordings a run should process.

    Resolution order: an explicit ``--participants-file`` (one
    ``sub[,ses]`` pair per line) takes precedence; otherwise
    ``--participant-label``/``--session-label`` are combined pairwise;
    otherwise every recording is discovered by scanning ``config.bids_dir``.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :returns: List of :class:`mrsiprep.io.bids.Recording`, not yet
        validated -- validity is checked later, per-recording, by
        :func:`run_participant_workflow`/:func:`validate_participant_inputs`.
    """
    if config.participants_file:
        return [Recording(sub, ses) for sub, ses in read_participant_pairs(config.participants_file)]
    subjects = config.participant_label or []
    sessions = config.session_label or []
    if subjects:
        if sessions:
            return [Recording(normalize_subject(sub), normalize_session(ses)) for sub in subjects for ses in sessions]
        return [Recording(normalize_subject(sub), None) for sub in subjects]
    return BIDSLayout.from_config(config).discover_recordings()


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
    layout = BIDSLayout.from_config(config)
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
    """Run the full mrsiprep pipeline for every recording matched by ``config``.

    This is the top-level entry point called by the CLI
    (:mod:`mrsiprep.cli.run`) for ``participant``-level runs. Steps:

    1. Ensure work/derivative directories exist.
    2. Resolve recordings via :func:`collect_recordings` and validate each
       one's inputs; failures are recorded as ``"skipped"`` and excluded
       from processing (other recordings still run).
    3. If ``config.longitudinal``, build one subject-level T1w template
       per subject with 2+ ready sessions, used to seed each session's
       T1w→MNI registration.
    4. Dispatch all ready recordings to the Nipype execution engine
       (:func:`mrsiprep.workflows.nipype_engine.run.execute_recordings_nipype`),
       which runs each recording's per-step cached workflow and reports
       ``"success"``/``"failed"`` per recording.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :returns: One :class:`RecordingStatus` per recording matched by
        ``config`` (empty list if none matched).
    """
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
    """Dry-run input validation for every recording matched by ``config``.

    Same discovery/validation logic as :func:`run_participant_workflow`
    (including the same preflight input-availability table) but never
    builds subject templates or dispatches to Nipype -- used by
    ``--validate-only`` to report which recordings are ready without
    running the pipeline.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :returns: One :class:`RecordingStatus` per recording matched by
        ``config``, with ``status`` either ``"failed"`` (validation
        failed; ``outputs`` empty) or ``"success"`` (validation passed;
        ``outputs`` populated with keys ``"t1w"``, ``"metabolites"``,
        ``"snr"``, ``"linewidth"``, ``"brainmask"`` -- nothing is
        actually processed).
    """
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


def run_reports_only_workflow(config) -> list[RecordingStatus]:
    """Rerun only QC/report generation for already-processed recordings.

    Same recording discovery/validation as :func:`run_participant_workflow`,
    but executes each recording's step sequence directly in-process --
    bypassing the Nipype DAG/node cache in
    :mod:`mrsiprep.workflows.nipype_engine` entirely -- instead of building
    and running a per-recording Nipype workflow. This is safe and correct
    because every expensive step (tissue segmentation, registration,
    parcellation, PVC, filtering) already self-skips via its own
    ``if out.exists() and not config.overwrite*: return`` guard; Nipype's
    own ``(step, config, subject, session)``-keyed node cache under
    ``--work-dir`` is redundant with (and more fragile than) that file-level
    gating, since it's invalidated by any config change or a cleared
    ``--work-dir``. Report/QC writers themselves always unconditionally
    re-render from whatever derivatives are on disk, so simply re-running
    the full step sequence -- without Nipype -- yields "recompute nothing
    that already exists, rewrite every report" for free, with no separate
    derivative-reconstruction logic needed.

    If a step's required upstream derivative is genuinely missing, that
    step computes it for real (same as a normal run would) rather than
    failing -- there is no separate pre-flight existence check, to avoid
    duplicating each step's own gating logic (see
    :mod:`mrsiprep.workflows.nipype_engine.nodes` for the source of truth).

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :returns: One :class:`RecordingStatus` per recording matched by
        ``config`` (empty list if none matched).
    """
    from mrsiprep.io.naming import prefix as name_prefix
    from mrsiprep.io.naming import subject_session_dir
    from mrsiprep.utils.debug import collect_timings, set_logbook, set_timing_sink
    from mrsiprep.utils.runtime_metrics import write_runtime_metrics
    from mrsiprep.workflows.nipype_engine.nodes import STEP_SEQUENCE

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

    for recording in ready:
        subject, session = recording.subject, recording.session
        tag = f"sub-{subject}" + (f" ses-{session}" if session else "")
        logbook = subject_session_dir(config.derivative_dir, subject, session, "logs") / f"{name_prefix(subject, session)}_desc-mrsiprep_log.txt"
        set_logbook(logbook)
        set_timing_sink(True)
        debug.always(f"[proc]START[/proc] {tag}")
        start = time.monotonic()
        try:
            ctx: dict = {"subject_template": subject_templates.get(subject)}
            for _name, step_fn in STEP_SEQUENCE:
                ctx = step_fn(config, subject, session, ctx)
            elapsed = time.monotonic() - start
            debug.always(f"[success]FINISHED[/success] {tag} in {_format_elapsed(elapsed)}")
            write_runtime_metrics(config, subject, session, collect_timings(), elapsed, status="success")
            statuses.append(RecordingStatus(subject, session, "success", outputs=ctx.get("outputs", {})))
        except Exception as exc:
            elapsed = time.monotonic() - start
            exc_summary = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
            debug.always(f"[failure]FAILED[/failure] {tag} after {_format_elapsed(elapsed)}: {exc_summary}")
            debug.exception(f"FAILED {tag} after {_format_elapsed(elapsed)}: {exc}", traceback.format_exc())
            write_runtime_metrics(config, subject, session, collect_timings(), elapsed, status="failed")
            if config.stop_on_first_crash:
                set_logbook(None)
                set_timing_sink(False)
                raise
            statuses.append(RecordingStatus(subject, session, "failed", error=str(exc)))
        finally:
            set_logbook(None)
            set_timing_sink(False)
    return statuses



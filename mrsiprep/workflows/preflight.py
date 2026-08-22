"""Pre-run input inventory and the preflight summary table.

Answers "what is present, what is missing, and what will be recomputed?" for
every selected recording *before* any processing starts, and renders that as
the console table shown at startup. Nothing here mutates state or writes
derivatives -- it only inspects the layout.

Orchestration lives in :mod:`mrsiprep.workflows.participant`; the processing
stages themselves live in :mod:`mrsiprep.workflows.steps`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from rich import box
from rich.table import Table

from mrsiprep.interfaces.freesurfer import freesurfer_subject_id, subject_dir_valid
from mrsiprep.io.bids import BIDSLayout
from mrsiprep.io.loaders import load_mrsi_inputs
from mrsiprep.utils.debug import Debug


@dataclass
class RecordingStatus:
    """Outcome of processing (or validating) one subject/session recording.

    :ivar subject: BIDS subject label, without the ``sub-`` prefix.
    :ivar session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :ivar status: One of ``"skipped"`` (failed validation before
        processing started), ``"success"``, or ``"failed"`` (raised
        during Nipype execution).
    :ivar outputs: Output paths produced for this recording, keyed by a
        short name (e.g. ``"t1w"``, ``"qc_summary"``, ``"regional_table"``);
        empty for skipped recordings.
    :ivar error: Human-readable error message, set when ``status`` is
        ``"skipped"`` or ``"failed"``.
    """

    subject: str
    session: str | None
    status: str
    outputs: dict = field(default_factory=dict)
    error: str | None = None


def _preflight_t1_status(layout, subject, session, config, check_integrity: bool):
    """Returns (t1_status, t1_corrupt) for the preflight T1w check."""
    from mrsiprep.utils.images import nifti_validity_error

    t1_path = layout.t1(subject, session, config.t1_pattern)
    t1_status = bool(t1_path and t1_path.exists())
    t1_corrupt = bool(t1_status and check_integrity and nifti_validity_error(t1_path))
    return t1_status, t1_corrupt


def _preflight_corrupt_items(inputs, t1_corrupt: bool, check_integrity: bool) -> list[str]:
    """Human-readable labels for every input file that failed a NIfTI validity check."""
    from mrsiprep.utils.images import nifti_validity_error

    if not check_integrity:
        return []
    corrupt_items = []
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
    return corrupt_items


def _preflight_tissue_label(layout, subject, session, config) -> str:
    """Rich-markup cell for the preflight table's 'Tissue files' column."""
    if config.tissue_backend != "existing":
        return "[cyan]AUTO[/cyan]"
    tissue_statuses = [bool(layout.cat12_probseg(subject, session, idx)) for idx in (1, 2, 3)]
    return " ".join(
        f"[{'green' if status else 'red'}]p{idx}[/{'green' if status else 'red'}]"
        for idx, status in enumerate(tissue_statuses, 1)
    )


def _preflight_transform_status(layout, subject, session, config) -> dict[str, bool]:
    """Which registration-transform stages already have all their files on disk."""
    transform_stages = ["mrsi", "anat"]
    if config.longitudinal:
        transform_stages.append("t1-template")
    transforms = {}
    for stage in transform_stages:
        stage_paths = layout.transform(subject, session, stage)
        transforms[stage] = bool(stage_paths and all(path.exists() for path in stage_paths))
    return transforms


def _preflight_freesurfer_status(layout, subject, session, config) -> bool | None:
    """FreeSurfer recon-all completeness, or None when this run doesn't need it."""
    if config.parcellation_mode != "chimera":
        return None
    raw_t1 = layout.raw_t1(subject, session)
    if raw_t1 is None:
        return False
    fs_subject = freesurfer_subject_id(raw_t1)
    return subject_dir_valid(config.freesurfer_dir, fs_subject)


def _gather_input_availability(config, subject: str, session: str | None) -> dict:
    layout = BIDSLayout.from_config(config)
    recording_id = f"sub-{subject}"
    if session:
        recording_id += f"_ses-{session}"

    check_integrity = not config.skip_file_integrity_check

    t1_status, t1_corrupt = _preflight_t1_status(layout, subject, session, config, check_integrity)
    inputs = load_mrsi_inputs(layout, subject, session, config.metabolites)
    corrupt_items = _preflight_corrupt_items(inputs, t1_corrupt, check_integrity)

    return {
        "recording_id": recording_id,
        "subject": subject,
        "session": session,
        "t1": t1_status,
        "mrsi_found": len(inputs.metabolite_maps),
        "mrsi_expected": len(config.metabolites),
        "crlb_found": len(inputs.crlb_maps),
        "snr": bool(inputs.snr_map),
        "fwhm": bool(inputs.linewidth_map),
        "brainmask": bool(inputs.brainmask),
        "tissue": _preflight_tissue_label(layout, subject, session, config),
        "transforms": _preflight_transform_status(layout, subject, session, config),
        "freesurfer": _preflight_freesurfer_status(layout, subject, session, config),
        "corrupt_items": corrupt_items,
    }


_PREFLIGHT_CHECK_MARK = "[green]✔[/green]"
_PREFLIGHT_CROSS_MARK = "[red]X[/red]"
_PREFLIGHT_PROC_MARK = "[orange3]PROC[/orange3]"
_PREFLIGHT_NA_MARK = "[grey58]N/A[/grey58]"


def _preflight_transform_columns(config) -> list[tuple[str, str]]:
    columns = [("mrsi", "MRSI→T1"), ("anat", "T1→MNI")]
    if config.longitudinal:
        columns.append(("t1-template", "Ses→Template"))
    return columns


def _build_preflight_table(config, transform_columns, show_integrity: bool, show_freesurfer: bool) -> Table:
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
    return table


def _preflight_row_cells(row: dict, transform_columns, show_integrity: bool, show_freesurfer: bool) -> list[str]:
    mrsi_color = "green" if row["mrsi_found"] == row["mrsi_expected"] else "red"
    crlb_color = "green" if row["crlb_found"] == row["mrsi_expected"] else "red"

    cells = [
        row["recording_id"],
        _PREFLIGHT_CHECK_MARK if row["t1"] else _PREFLIGHT_CROSS_MARK,
        f"[{mrsi_color}]{row['mrsi_found']}/{row['mrsi_expected']}[/{mrsi_color}]",
        f"[{crlb_color}]{row['crlb_found']}/{row['mrsi_expected']}[/{crlb_color}]",
        _PREFLIGHT_CHECK_MARK if row["snr"] else _PREFLIGHT_CROSS_MARK,
        _PREFLIGHT_CHECK_MARK if row["fwhm"] else _PREFLIGHT_CROSS_MARK,
        _PREFLIGHT_CHECK_MARK if row["brainmask"] else _PREFLIGHT_PROC_MARK,
        row["tissue"],
    ]

    if show_integrity:
        corrupt_items = row.get("corrupt_items") or []
        cells.append(f"[red]CORRUPT ({', '.join(corrupt_items)})[/red]" if corrupt_items else _PREFLIGHT_CHECK_MARK)

    if show_freesurfer:
        if row["freesurfer"] is None:
            cells.append(_PREFLIGHT_NA_MARK)
        else:
            cells.append(_PREFLIGHT_CHECK_MARK if row["freesurfer"] else _PREFLIGHT_PROC_MARK)

    for stage_key, _ in transform_columns:
        cells.append(_PREFLIGHT_CHECK_MARK if row["transforms"].get(stage_key, False) else _PREFLIGHT_PROC_MARK)

    return cells


def _preflight_missing_items(row: dict, config) -> list[str]:
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
    if config.tissue_backend == "existing" and "red" in row["tissue"]:
        missing_items.append("Tissue")
    if row.get("corrupt_items"):
        missing_items.append(f"CORRUPT ({', '.join(row['corrupt_items'])})")
    return missing_items


def _report_preflight_summary(debug: Debug, summaries: list[dict], missing_recordings: list[str], total_missing_files: int) -> None:
    if missing_recordings:
        debug.error(
            f"Detected {total_missing_files} missing or incomplete file categories across {len(missing_recordings)}/{len(summaries)} recordings. "
            f"Affected recordings: {', '.join(missing_recordings)}"
        )
    else:
        debug.success("All required inputs are available for the selected recordings.")


def _report_cpu_budget(debug: Debug, config) -> None:
    nproc, nthreads, cpu_warning = config.resolve_cpu_budget()
    if cpu_warning:
        debug.always(f"[warning]WARNING:[/warning] {cpu_warning}")
    else:
        debug.always(f"CPU budget: --nproc {nproc} x --nthreads {nthreads} = {nproc * nthreads} threads (of {os.cpu_count()} available).")


def _render_preflight_table(config, summaries: list[dict], debug: Debug) -> None:
    transform_columns = _preflight_transform_columns(config)
    show_freesurfer = any(row["freesurfer"] is not None for row in summaries)
    show_integrity = not config.skip_file_integrity_check

    table = _build_preflight_table(config, transform_columns, show_integrity, show_freesurfer)

    total_missing_files = 0
    missing_recordings = []
    for row in summaries:
        table.add_row(*_preflight_row_cells(row, transform_columns, show_integrity, show_freesurfer))
        missing_items = _preflight_missing_items(row, config)
        if missing_items:
            total_missing_files += len(missing_items)
            missing_recordings.append(row["recording_id"])

    debug.separator()
    debug.title("Preflight input availability")
    debug.console.print(table)
    _report_preflight_summary(debug, summaries, missing_recordings, total_missing_files)
    _report_cpu_budget(debug, config)



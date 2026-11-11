"""Cross-subject ``report_overview.html``: one row per recording this
project's BIDS directory could in principle produce, each linking to that
recording's own report.

Rebuilt from scratch on every call (cheap: one ``load_mrsi_inputs`` scan per
recording, no heavy processing) rather than incrementally updated, so it
never drifts from the derivatives tree's actual on-disk state -- including
recordings processed in an earlier, separate invocation. Called once per
recording, right after that recording's own HTML report is written (see
:func:`mrsiprep.workflows.reports.run_reports_workflow`), so it updates
live as a batch runs.
"""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.bids import BIDSLayout
from mrsiprep.io.loaders import load_mrsi_inputs
from mrsiprep.io.naming import coverage_report_html, mrsi_derivative, prefix, provenance_derivative, subject_session_dir
from mrsiprep.utils.misc import normalize_session, normalize_subject
from mrsiprep.utils.version import mrsiprep_version

_STATUS_SUCCESS = "success"
_STATUS_FAILED = "failed"
_STATUS_UNPROCESSED = "unprocessed"
_STATUS_NO_DATA = "no_data"

_STATUS_BADGE = {
    _STATUS_SUCCESS: "<span class='badge ok' title='Processed successfully'>&#10004;</span>",
    _STATUS_FAILED: "<span class='badge fail' title='MRSI data found but the run failed or is incomplete'>&#10006;</span>",
    _STATUS_UNPROCESSED: "<span class='badge proc' title='MRSI raw data found, not yet processed'>&#8635;</span>",
    _STATUS_NO_DATA: "<span class='badge nodata' title='No MRSI data found'>&ndash;</span>",
}

_OVERVIEW_FILENAME = "report_overview.html"


def _expected_recordings(config) -> list[tuple[str, str | None]]:
    """Every (subject, session) this project's BIDS directory names, via the
    same resolution :func:`mrsiprep.workflows.participant.collect_recordings`
    uses for an unfiltered run (participants TSV if present, else a directory
    scan) -- not the current invocation's ``--participant-label`` subset,
    so the overview always covers the whole project regardless of how many
    subjects this particular run touched."""
    recordings = BIDSLayout.from_config(config).discover_recordings()
    return sorted({(normalize_subject(r.subject), normalize_session(r.session)) for r in recordings})


def _log_indicates_failure(log_path: Path) -> bool:
    if not log_path.is_file():
        return False
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "Traceback (most recent call last)" in text or "CRITICAL" in text


def _median_dice(config, subject: str, session: str | None) -> float | None:
    tsv = mrsi_derivative(config.derivative_dir, subject, session, desc="ventricleqc", suffix_override="tsv")
    if not tsv.is_file():
        return None
    try:
        for line in tsv.read_text(encoding="utf-8").splitlines()[1:]:
            fields = line.split("\t")
            if fields and fields[0] == "median":
                return float(fields[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _recording_row(config, layout, subject: str, session: str | None) -> dict:
    report = coverage_report_html(config.derivative_dir, subject, session)
    provenance = provenance_derivative(config.derivative_dir, subject, session)
    log_path = subject_session_dir(config.derivative_dir, subject, session, "logs") / f"{prefix(subject, session)}_desc-mrsiprep_log.txt"

    mrsi_found = len(load_mrsi_inputs(layout, subject, session, config.metabolites).metabolite_maps)

    if mrsi_found == 0:
        status = _STATUS_NO_DATA
    elif report.is_file() and (provenance.is_file() or not _log_indicates_failure(log_path)):
        # Reports are written just before provenance.json within the same
        # recording's run (see nipype_engine/nodes.py), so a report with no
        # provenance yet and no error in the log is this recording's own
        # in-flight run, not a failure -- treat it the same as success rather
        # than flashing red for a few seconds on every live update.
        status = _STATUS_SUCCESS
    elif log_path.is_file():
        # A log exists but no (valid) report: a run was attempted and either
        # crashed or hasn't reached the reports step yet.
        status = _STATUS_FAILED
    else:
        status = _STATUS_UNPROCESSED

    return {
        "subject": subject,
        "session": session,
        "status": status,
        "report": report if report.is_file() else None,
        "median_dice": _median_dice(config, subject, session) if status == _STATUS_SUCCESS else None,
    }


def _recording_id(subject: str, session: str | None) -> str:
    return prefix(subject, session)


def _row_html(row: dict, derivative_dir: Path) -> str:
    recording_id = _recording_id(row["subject"], row["session"])
    badge = _STATUS_BADGE[row["status"]]
    dice = f"{row['median_dice']:.3f}" if row["median_dice"] is not None else "&ndash;"
    if row["report"] is not None:
        href = row["report"].relative_to(derivative_dir).as_posix()
        label = f"<a href='{href}' target='_blank' rel='noopener'>{recording_id}</a>"
    else:
        label = recording_id
    return f"<tr><td>{label}</td><td class='center'>{badge}</td><td class='center'>{dice}</td></tr>"


_STYLE = (
    "body{font-family:Arial,sans-serif;margin:2rem;line-height:1.4}"
    "table{border-collapse:collapse;width:100%;max-width:640px}"
    "td,th{border:1px solid #ddd;padding:4px 10px;text-align:left}"
    "th{background:#f3f3f3;cursor:pointer}"
    ".center{text-align:center}"
    ".badge{font-weight:bold}"
    ".badge.ok{color:#2e8b2e}"
    ".badge.fail{color:#c0392b}"
    ".badge.proc{color:#d68910;display:inline-block;animation:spin 2s linear infinite}"
    ".badge.nodata{color:#999}"
    "@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}"
    ".legend{color:#555;font-size:0.9rem;margin-bottom:1rem}"
)


def update_report_overview(config) -> Path:
    """(Re)build ``<derivative_dir>/report_overview.html`` from the current
    on-disk state of every recording this project's BIDS directory names.

    Safe to call repeatedly (e.g. once per recording during a batch run);
    always reflects the full project, not just the recordings the calling
    invocation itself touched.
    """
    layout = BIDSLayout.from_config(config)
    derivative_dir = Path(config.derivative_dir)
    derivative_dir.mkdir(parents=True, exist_ok=True)

    rows = [_recording_row(config, layout, subject, session) for subject, session in _expected_recordings(config)]
    rows.sort(key=lambda r: (r["subject"], r["session"] or ""))

    n_success = sum(r["status"] == _STATUS_SUCCESS for r in rows)
    n_failed = sum(r["status"] == _STATUS_FAILED for r in rows)
    n_unprocessed = sum(r["status"] == _STATUS_UNPROCESSED for r in rows)
    n_no_data = sum(r["status"] == _STATUS_NO_DATA for r in rows)

    lines = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><title>MRSIPrep report overview</title>",
        f"<style>{_STYLE}</style>",
        "<script>",
        "function sortTable(colIndex){"
        "const table=document.getElementById('overview');"
        "const rows=Array.from(table.tBodies[0].rows);"
        "const asc=table.dataset.sortCol==String(colIndex)&&table.dataset.sortDir!=='asc';"
        "rows.sort((a,b)=>{"
        "const x=a.cells[colIndex].innerText.trim();const y=b.cells[colIndex].innerText.trim();"
        "return asc?x.localeCompare(y):y.localeCompare(x);"
        "});"
        "rows.forEach(r=>table.tBodies[0].appendChild(r));"
        "table.dataset.sortCol=colIndex;table.dataset.sortDir=asc?'asc':'desc';"
        "}",
        "</script>",
        "</head><body>",
        "<h1>MRSIPrep report overview</h1>",
        f"<p>MRSIPrep version: <code>{mrsiprep_version()}</code></p>",
        f"<p>BIDS directory: <code>{config.bids_dir}</code></p>",
        "<p class='legend'>"
        f"{_STATUS_BADGE[_STATUS_SUCCESS]} processed ({n_success}) &nbsp; "
        f"{_STATUS_BADGE[_STATUS_FAILED]} failed/incomplete ({n_failed}) &nbsp; "
        f"{_STATUS_BADGE[_STATUS_UNPROCESSED]} raw data found, not yet processed ({n_unprocessed}) &nbsp; "
        f"{_STATUS_BADGE[_STATUS_NO_DATA]} no MRSI data found ({n_no_data})"
        "</p>",
        "<table id='overview'>",
        "<thead><tr>"
        "<th onclick='sortTable(0)'>Recording</th>"
        "<th class='center' onclick='sortTable(1)'>Status</th>"
        "<th class='center' onclick='sortTable(2)'>Median ventricle Dice</th>"
        "</tr></thead>",
        "<tbody>",
    ]
    lines.extend(_row_html(row, derivative_dir) for row in rows)
    lines.extend(["</tbody>", "</table>", "</body></html>"])

    out = derivative_dir / _OVERVIEW_FILENAME
    out.write_text("\n".join(lines), encoding="utf-8")
    return out

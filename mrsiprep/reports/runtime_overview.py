"""Pipeline runtime/timing QC section (Runtime tab).

Built from the process-local step-timing accumulator in
:mod:`mrsiprep.utils.debug` (``collect_timings()``), which every
``Debug.step()`` call appends to automatically -- no per-step
instrumentation elsewhere in the pipeline needed. Since this section is
built by the "reports" node itself, the last step's own duration (the
report generation currently in progress) can't be included -- everything
before it can.
"""

from __future__ import annotations


def _format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remainder:04.1f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {remainder:04.1f}s"


def build_runtime_qc_sections(config, step_timings: list[dict]) -> list[tuple[str, str]]:
    """Returns the Runtime tab's (heading, body_html) sections: a table of
    per-step wall-clock duration, the run's total so far, and the
    nproc/nthreads context it ran under."""
    if not step_timings:
        return [("Runtime", "<p>No timing data recorded for this run.</p>")]

    total = sum(entry["seconds"] for entry in step_timings)
    rows = "".join(
        f"<tr><td>{entry['step']}</td><td>{_format_seconds(entry['seconds'])}</td>"
        f"<td>{100 * entry['seconds'] / total:.1f}%</td></tr>"
        for entry in step_timings
    )
    table = (
        "<table><tr><th>Step</th><th>Duration</th><th>% of total</th></tr>"
        + rows
        + f"<tr><td><strong>Total (through report generation)</strong></td><td><strong>{_format_seconds(total)}</strong></td><td>100.0%</td></tr>"
        + "</table>"
    )
    context = (
        f"<p>nproc: <code>{getattr(config, 'nproc', 'n/a')}</code> &nbsp;|&nbsp; "
        f"nthreads: <code>{getattr(config, 'nthreads', 'n/a')}</code></p>"
    )
    note = (
        "<p>Excludes this report-generation step's own duration (not yet known while it's still running) "
        "and any time spent before this recording's pipeline started (e.g. queued behind other recordings "
        "under <code>--nproc</code>).</p>"
    )
    return [("Per-step duration", context + note + table)]

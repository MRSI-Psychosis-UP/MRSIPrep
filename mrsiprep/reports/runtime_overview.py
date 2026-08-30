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


_OUTCOME_STYLE = {
    "processed": ("PROC", "#137333"),
    "failed": ("FAILED", "#c5221f"),
    "skipped": ("SKIPPED", "#8a8a8a"),
}


def _outcome_cell(outcome: str) -> str:
    label, colour = _OUTCOME_STYLE.get(outcome, (outcome.upper(), "#8a8a8a"))
    return f"<td style='color:{colour};font-weight:600'>{label}</td>"


def _skipped_steps(config, timed_steps: set) -> list[dict]:
    """Steps the config gated out, which therefore have no timing row.

    A skipped step never enters ``Debug.step()``, so it is invisible to the
    timing sink -- but "not in the table" and "ran instantly" look identical
    to a reader. The provenance trace already derives what was gated and why,
    so reuse it rather than threading state through the workflow.
    """
    try:
        from mrsiprep.utils.provenance import pipeline_trace

        trace = pipeline_trace(config)
    except Exception:
        # The trace is derived from config flags; if that cannot be built the
        # timings are still worth showing on their own.
        return []
    return [
        {"step": entry["step"], "seconds": None, "outcome": "skipped", "reason": entry.get("reason", "")}
        for entry in trace
        if not entry.get("ran", True) and entry["step"] not in timed_steps
    ]


def build_runtime_qc_sections(config, step_timings: list[dict]) -> list[tuple[str, str]]:
    """Returns the Runtime tab's (heading, body_html) sections: a table of
    per-step wall-clock duration and outcome, the run's total so far, and the
    nproc/nthreads context it ran under."""
    if not step_timings:
        return [("Runtime", "<p>No timing data recorded for this run.</p>")]

    total = sum(entry["seconds"] for entry in step_timings)
    entries = list(step_timings) + _skipped_steps(config, {entry["step"] for entry in step_timings})

    rows = ""
    for entry in entries:
        seconds = entry.get("seconds")
        if seconds is None:
            duration, share = "-", "-"
        else:
            duration = _format_seconds(seconds)
            share = f"{100 * seconds / total:.1f}%" if total else "-"
        reason = entry.get("reason") or ""
        step = f"{entry['step']}<br><small style='color:#8a8a8a'>{reason}</small>" if reason else entry["step"]
        rows += (
            f"<tr><td>{step}</td>{_outcome_cell(entry.get('outcome', 'processed'))}"
            f"<td>{duration}</td><td>{share}</td></tr>"
        )

    table = (
        "<table><tr><th>Step</th><th>Outcome</th><th>Duration</th><th>% of total</th></tr>"
        + rows
        + "<tr><td><strong>Total (through report generation)</strong></td><td></td>"
        + f"<td><strong>{_format_seconds(total)}</strong></td><td>100.0%</td></tr>"
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

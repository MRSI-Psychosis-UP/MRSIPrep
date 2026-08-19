"""Per-recording runtime/timing metrics, written alongside provenance.json.

Captured from the process-local step-timing accumulator in
:mod:`mrsiprep.utils.debug` (`set_timing_sink`/`collect_timings`), which
`Debug.step()` appends to for every pipeline stage automatically -- no
per-call-site instrumentation needed.
"""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from mrsiprep.io.naming import runtime_metrics_derivative


def write_runtime_metrics(
    config,
    subject: str,
    session: str | None,
    step_timings: list[dict],
    total_seconds: float,
    status: str,
) -> Path:
    """Writes a `desc-runtimemetrics` JSON with per-step durations, total
    wall-clock time, and run context (nproc/nthreads, hostname)."""
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "total_seconds": total_seconds,
        "steps": step_timings,
        "nproc": getattr(config, "nproc", None),
        "nthreads": getattr(config, "nthreads", None),
        "hostname": platform.node(),
    }
    out = runtime_metrics_derivative(config.derivative_dir, subject, session)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def read_runtime_metrics(config, subject: str, session: str | None) -> dict | None:
    path = runtime_metrics_derivative(config.derivative_dir, subject, session)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

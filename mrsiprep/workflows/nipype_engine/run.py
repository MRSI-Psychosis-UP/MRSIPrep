"""Execution entry point for the Nipype engine.

Builds a per-recording Nipype workflow (:mod:`build`) and runs it, reproducing
the START/FINISHED/timing/``RecordingStatus`` bookkeeping expected by
``run_participant_workflow``. The per-step ``[  PROC  ]`` / ``[   ✓    ]`` lines
are emitted for free: the nodes call the existing ``_step_*`` functions, which
use ``debug.step()`` internally.

Cross-recording parallelism uses a ``ProcessPoolExecutor`` gated on ``--nproc``,
which keeps per-recording batch-safety/error isolation. The within-recording DAG
is an inherent data-dependency chain, so each recording workflow runs with the
Linear plugin.
"""

from __future__ import annotations

import time
import traceback
from typing import TYPE_CHECKING

from mrsiprep.utils.debug import Debug
from mrsiprep.utils.logging import LOGGER

if TYPE_CHECKING:
    from mrsiprep.io.bids import Recording
    from mrsiprep.workflows.participant import RecordingStatus


def _configure_nipype_logging(config) -> None:
    """Keep Nipype's own logging out of the console unless verbose is high.

    Also disables etelemetry's network version check, which would otherwise
    stall/emit noise on first import in offline container runs.
    """
    import os

    os.environ.setdefault("NIPYPE_NO_ET", "1")
    os.environ.setdefault("NO_ET", "1")

    from nipype import config as ncfg
    from nipype import logging as nlogging

    level = "INFO" if config.verbose >= 3 else "CRITICAL"
    ncfg.update_config(
        {"logging": {"workflow_level": level, "interface_level": level, "utils_level": level}}
    )
    nlogging.update_logging(ncfg)


def execute_recordings_nipype(config, ready: "list[Recording]", subject_templates: dict | None = None) -> "list[RecordingStatus]":
    """Run the ready recordings through the Nipype engine.

    Serial when ``--nproc <= 1``; otherwise fan out across recordings with a
    ProcessPoolExecutor (each worker builds and runs its own recording DAG).

    ``subject_templates`` maps subject -> precomputed ``SubjectTemplateResult``
    (see ``mrsiprep.workflows.participant._build_subject_templates``), built
    once per subject ahead of time when ``--longitudinal`` is on. Subjects
    absent from the dict fall back to direct per-session T1-to-MNI
    registration.
    """
    _configure_nipype_logging(config)
    subject_templates = subject_templates or {}

    if config.nproc <= 1:
        return [
            _run_one_recording_nipype(config, rec.subject, rec.session, subject_templates.get(rec.subject))
            for rec in ready
        ]

    from concurrent.futures import ProcessPoolExecutor, as_completed

    statuses: list = []
    with ProcessPoolExecutor(max_workers=config.nproc) as executor:
        futures = {
            executor.submit(_run_one_recording_nipype, config, rec.subject, rec.session, subject_templates.get(rec.subject)): rec
            for rec in ready
        }
        for future in as_completed(futures):
            statuses.append(future.result())
    return statuses


def _run_one_recording_nipype(config, subject: str, session: str | None, subject_template=None) -> "RecordingStatus":
    from mrsiprep.io.naming import prefix as name_prefix
    from mrsiprep.io.naming import subject_session_dir
    from mrsiprep.utils.debug import set_logbook
    from mrsiprep.workflows.nipype_engine.build import TERMINAL_NODE, build_recording_workflow
    from mrsiprep.workflows.participant import RecordingStatus, _format_elapsed

    _configure_nipype_logging(config)

    # Per-recording logbook inside the subject/session output folder; every
    # timestamped Debug message is mirrored here for the duration of this run.
    logbook = subject_session_dir(config.derivative_dir, subject, session, "logs") / f"{name_prefix(subject, session)}_desc-mrsiprep_log.txt"
    set_logbook(logbook)

    debug = Debug(verbose=config.verbose)
    msg = f"sub-{subject}" + (f" ses-{session}" if session else "")
    debug.separator()
    debug.always(f"[proc]START[/proc] {msg}")
    LOGGER.info("START %s", msg)
    start = time.monotonic()
    try:
        wf = build_recording_workflow(config, subject, session, subject_template=subject_template)
        exec_graph = wf.run(plugin="Linear")
        outputs = _terminal_outputs(exec_graph, TERMINAL_NODE)
        elapsed = time.monotonic() - start
        debug.always(f"[success]FINISHED[/success] {msg} in {_format_elapsed(elapsed)}")
        LOGGER.info("FINISHED %s in %s", msg, _format_elapsed(elapsed))
        return RecordingStatus(subject, session, "success", outputs=outputs)
    except Exception as exc:  # batch-safe failure, unless --stop-on-first-crash
        elapsed = time.monotonic() - start
        debug.always(f"[failure]FAILED[/failure] {msg} after {_format_elapsed(elapsed)}: {exc}")
        LOGGER.error("FAILED %s after %s: %s", msg, _format_elapsed(elapsed), exc)
        if config.verbose >= 2:
            LOGGER.error(traceback.format_exc())
        if config.stop_on_first_crash:
            raise
        return RecordingStatus(subject, session, "failed", error=str(exc))
    finally:
        set_logbook(None)


def _terminal_outputs(exec_graph, terminal_name: str) -> dict:
    """Read ctx['outputs'] off the terminal node's result in the executed graph."""
    for node in exec_graph.nodes():
        if node.name == terminal_name:
            ctx = node.result.outputs.ctx
            return ctx.get("outputs", {}) if isinstance(ctx, dict) else {}
    return {}

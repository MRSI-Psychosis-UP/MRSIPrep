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

Under ``--nproc > 1``, each worker is a separate OS process; letting every
worker print its own step lines directly to the shared terminal makes them
interleave/garble (worst with the live spinner, since two processes race to
move the same cursor). Instead, each worker sets a process-local status
queue (``mrsiprep.utils.debug.set_status_queue``, read by
``Debug._emit_status``) and pushes step transitions there instead of
printing; only this module's coordinating main-process thread ever writes to
the terminal, rendering one live-updating row per subject/session. This is
process-local rather than threaded through Nipype's ``ctx`` deliberately --
see ``build_recording_workflow``'s docstring for why.
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
    In the parallel case, a live per-subject status table (one row per
    recording, updated in place) replaces the plain scrolling step lines --
    see ``_run_live_status_table``.

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

    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor, as_completed

    manager = multiprocessing.Manager()
    status_queue = manager.Queue()
    tags = [f"sub-{rec.subject}" + (f" ses-{rec.session}" if rec.session else "") for rec in ready]
    stop_listener, listener_thread = _start_live_status_table(config, tags, status_queue)

    statuses: list = []
    try:
        with ProcessPoolExecutor(max_workers=config.nproc) as executor:
            futures = {
                executor.submit(
                    _run_one_recording_nipype, config, rec.subject, rec.session, subject_templates.get(rec.subject), status_queue
                ): rec
                for rec in ready
            }
            for future in as_completed(futures):
                statuses.append(future.result())
    finally:
        stop_listener.set()
        listener_thread.join(timeout=5)
        manager.shutdown()
    return statuses


def _start_live_status_table(config, tags: "list[str]", status_queue):
    """Spin up a background thread that drains ``status_queue`` and renders a
    single ``rich.Live`` table with one row per recording (identified by its
    ``Debug`` tag), replacing the interleaved per-worker step lines.

    Falls back to no live table (workers print nothing extra either, since
    they were handed the queue) when verbosity is 0 or stdout isn't a real
    terminal -- a redrawing table on a piped/non-interactive stream (e.g.
    Docker logs) would just spam raw escape codes.
    """
    import sys
    import threading

    from rich import box
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table

    stop_event = threading.Event()

    if config.verbose < 1 or not sys.stdout.isatty():
        # Still drain the queue (so it doesn't fill up unbounded) but render
        # nothing; per-recording logbooks already captured everything.
        def _drain_only():
            while not stop_event.is_set():
                try:
                    status_queue.get(timeout=0.2)
                except Exception:
                    continue

        thread = threading.Thread(target=_drain_only, daemon=True)
        thread.start()
        return stop_event, thread

    console = Console()
    rows: dict[str, dict] = {tag: {"step": "queued", "state": "queued", "elapsed": None} for tag in tags}
    start_times: dict[str, float] = {}

    def _render() -> Table:
        table = Table(box=box.SIMPLE_HEAVY, show_lines=False, title="MRSIPrep -- parallel recordings")
        table.add_column("Recording", style="cyan", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Current step", no_wrap=True)
        table.add_column("Elapsed", justify="right", no_wrap=True)
        for tag in tags:
            row = rows[tag]
            state = row["state"]
            color = {"queued": "grey58", "running": "orange3", "done": "green", "failed": "bold red"}.get(state, "white")
            elapsed = row["elapsed"]
            elapsed_str = f"{elapsed:.0f}s" if elapsed is not None else "-"
            table.add_row(tag, f"[{color}]{state.upper()}[/{color}]", row["step"], elapsed_str)
        return table

    def _listen():
        with Live(_render(), console=console, refresh_per_second=4) as live:
            while not stop_event.is_set():
                try:
                    tag, kind, message = status_queue.get(timeout=0.2)
                except Exception:
                    continue
                row = rows.setdefault(tag, {"step": "", "state": "running", "elapsed": None})
                if kind == "always" and "START" in message:
                    row["state"] = "running"
                    row["step"] = "starting"
                    start_times[tag] = time.monotonic()
                elif kind == "always" and "FINISHED" in message:
                    row["state"] = "done"
                    row["step"] = "finished"
                    if tag in start_times:
                        row["elapsed"] = time.monotonic() - start_times[tag]
                elif kind == "always" and "FAILED" in message:
                    row["state"] = "failed"
                    row["step"] = message
                    if tag in start_times:
                        row["elapsed"] = time.monotonic() - start_times[tag]
                elif kind == "step":
                    row["state"] = "running"
                    row["step"] = message
                elif kind == "step_done":
                    row["step"] = f"{message} (done)"
                elif kind == "step_failed":
                    row["state"] = "failed"
                    row["step"] = f"{message} (failed)"
                if tag in start_times and row["state"] == "running":
                    row["elapsed"] = time.monotonic() - start_times[tag]
                live.update(_render())
            live.update(_render())

    thread = threading.Thread(target=_listen, daemon=True)
    thread.start()
    return stop_event, thread


def _run_one_recording_nipype(config, subject: str, session: str | None, subject_template=None, status_queue=None) -> "RecordingStatus":
    from mrsiprep.io.naming import prefix as name_prefix
    from mrsiprep.io.naming import subject_session_dir
    from mrsiprep.utils.debug import set_logbook, set_status_queue
    from mrsiprep.workflows.nipype_engine.build import TERMINAL_NODE, build_recording_workflow
    from mrsiprep.workflows.participant import RecordingStatus, _format_elapsed

    _configure_nipype_logging(config)

    # Per-recording logbook inside the subject/session output folder; every
    # timestamped Debug message is mirrored here for the duration of this run.
    logbook = subject_session_dir(config.derivative_dir, subject, session, "logs") / f"{name_prefix(subject, session)}_desc-mrsiprep_log.txt"
    set_logbook(logbook)
    # Process-local, not threaded through ctx -- see build_recording_workflow's
    # docstring for why (Nipype deep-copies ctx between nodes; deep-copying a
    # Manager Queue proxy fails).
    set_status_queue(status_queue)

    tag = f"sub-{subject}" + (f" ses-{session}" if session else "")
    debug = Debug(verbose=config.verbose)
    if status_queue is None:
        debug.separator()
    msg = tag
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
        # str(exc) can itself be a multi-line blob (e.g. FreeSurferError/
        # ChimeraError embed the failed subprocess's full captured stdout) --
        # keep only the first line on the always-shown console summary; the
        # full exception text and traceback still go to the per-recording
        # logbook via debug.exception() below, and to the failure's `error`
        # field on the returned status either way.
        exc_summary = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
        debug.always(f"[failure]FAILED[/failure] {msg} after {_format_elapsed(elapsed)}: {exc_summary}")
        LOGGER.error("FAILED %s after %s: %s", msg, _format_elapsed(elapsed), exc_summary)
        debug.exception(f"FAILED {msg} after {_format_elapsed(elapsed)}: {exc}", traceback.format_exc())
        if config.stop_on_first_crash:
            raise
        return RecordingStatus(subject, session, "failed", error=str(exc))
    finally:
        set_logbook(None)
        set_status_queue(None)


def _terminal_outputs(exec_graph, terminal_name: str) -> dict:
    """Read ctx['outputs'] off the terminal node's result in the executed graph."""
    for node in exec_graph.nodes():
        if node.name == terminal_name:
            ctx = node.result.outputs.ctx
            return ctx.get("outputs", {}) if isinstance(ctx, dict) else {}
    return {}

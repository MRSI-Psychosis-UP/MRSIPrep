"""MRSIPrep command entry point."""

from __future__ import annotations

import os
import sys

from mrsiprep.cli.parser import parse_args, print_presets
from mrsiprep.utils.banner import print_banner
from mrsiprep.utils.debug import Debug
from mrsiprep.utils.logging import setup_logging
from mrsiprep.utils.provenance import check_external_software
from mrsiprep.workflows.participant import run_participant_workflow, run_reports_only_workflow, validate_participant_inputs


def _recording_label(status) -> str:
    return f"sub-{status.subject}" + (f" ses-{status.session}" if status.session else "")


def _split_by_status(statuses):
    failed = [status for status in statuses if status.status != "success"]
    succeeded = [status for status in statuses if status.status == "success"]
    return succeeded, failed


def _run_validate_only(config, logger) -> int:
    statuses = validate_participant_inputs(config)
    succeeded, failed = _split_by_status(statuses)
    logger.info("MRSIPrep input validation finished: %d valid, %d invalid", len(succeeded), len(failed))
    for status in failed:
        logger.error("INVALID %s: %s", _recording_label(status), status.error)
    return 1 if failed else 0


def _run_participant(config, logger) -> int:
    statuses = run_participant_workflow(config)
    succeeded, failed = _split_by_status(statuses)
    logger.info("MRSIPrep finished: %d succeeded, %d failed", len(succeeded), len(failed))
    for status in failed:
        logger.error("FAILED %s: %s", _recording_label(status), status.error)
    return 1 if failed and not succeeded else 0


def _run_reports_only(config, logger) -> int:
    statuses = run_reports_only_workflow(config)
    succeeded, failed = _split_by_status(statuses)
    logger.info("MRSIPrep reports-only finished: %d succeeded, %d failed", len(succeeded), len(failed))
    for status in failed:
        logger.error("FAILED %s: %s", _recording_label(status), status.error)
    return 1 if failed and not succeeded else 0


#: Native thread-pool limits honoured by the libraries the pipeline loads.
#: ITK is set per-call in interfaces/ants.py; these cover the rest.
_THREAD_LIMIT_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def _apply_resolved_cpu_budget(config, logger) -> None:
    nproc, nthreads, cpu_warning = config.resolve_cpu_budget()
    if cpu_warning:
        logger.warning(cpu_warning)
    config.nproc, config.nthreads = nproc, nthreads

    # Without this, OpenMP and OpenBLAS each default to the machine's full core
    # count *inside every worker*, so --nproc 4 --nthreads 8 really asks for
    # 4 x 32 threads on a 32-core host. That oversubscription is why a worker
    # could sit at a fraction of a core while thrashing, and it is independent
    # of the fork deadlock fixed in nipype_engine/run.py. An explicit setting
    # by the user wins: they may be tuning deliberately.
    for name in _THREAD_LIMIT_VARS:
        os.environ.setdefault(name, str(config.nthreads))


def main(argv: list[str] | None = None) -> int:
    print_banner()
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--list-presets" in argv:
        print_presets()
        return 0

    config = parse_args(argv)
    logger = setup_logging(config.verbose, log_dir=config.logs_dir)
    _apply_resolved_cpu_budget(config, logger)

    if config.analysis_level != "participant":
        logger.error("Only participant analysis level is currently supported.")
        return 2
    if config.check_external_libs:
        ok = check_external_software(Debug(verbose=config.verbose), config)
        return 0 if ok else 1
    if config.validate_only:
        return _run_validate_only(config, logger)
    if config.reports_only:
        return _run_reports_only(config, logger)
    return _run_participant(config, logger)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

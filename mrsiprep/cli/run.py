"""MRSIPrep command entry point."""

from __future__ import annotations

import sys

from mrsiprep.cli.parser import parse_args
from mrsiprep.utils.banner import print_banner
from mrsiprep.utils.debug import Debug
from mrsiprep.utils.logging import setup_logging
from mrsiprep.utils.provenance import check_external_software
from mrsiprep.workflows.participant import run_participant_workflow, validate_participant_inputs


def main(argv: list[str] | None = None) -> int:
    print_banner()
    config = parse_args(argv)
    logger = setup_logging(config.verbose, log_dir=config.logs_dir)
    nproc, nthreads, cpu_warning = config.resolve_cpu_budget()
    if cpu_warning:
        logger.warning(cpu_warning)
    config.nproc, config.nthreads = nproc, nthreads
    if config.analysis_level != "participant":
        logger.error("Only participant analysis level is currently supported.")
        return 2
    if config.check_external_libs:
        debug = Debug(verbose=config.verbose)
        ok = check_external_software(debug, config)
        return 0 if ok else 1
    if config.validate_only:
        statuses = validate_participant_inputs(config)
        failed = [status for status in statuses if status.status != "success"]
        succeeded = [status for status in statuses if status.status == "success"]
        logger.info("MRSIPrep input validation finished: %d valid, %d invalid", len(succeeded), len(failed))
        for status in failed:
            logger.error("INVALID sub-%s%s: %s", status.subject, f" ses-{status.session}" if status.session else "", status.error)
        return 1 if failed else 0
    statuses = run_participant_workflow(config)
    failed = [status for status in statuses if status.status != "success"]
    succeeded = [status for status in statuses if status.status == "success"]
    logger.info("MRSIPrep finished: %d succeeded, %d failed", len(succeeded), len(failed))
    for status in failed:
        logger.error("FAILED sub-%s%s: %s", status.subject, f" ses-{status.session}" if status.session else "", status.error)
    return 1 if failed and not succeeded else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

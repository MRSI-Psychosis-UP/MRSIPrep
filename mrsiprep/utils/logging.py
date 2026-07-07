"""Small logging helpers for command-line workflows."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler


def setup_logging(verbose: int | bool = 1, log_dir: str | Path | None = None) -> logging.Logger:
    verbose = int(verbose)
    console_level = logging.DEBUG if verbose >= 2 else logging.INFO
    logger = logging.getLogger("mrsiprep")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Docker's stderr is often not a TTY, which makes rich (and plain ANSI)
    # color auto-detection disable itself; force it on unless NO_COLOR is set.
    force_color = not os.environ.get("NO_COLOR")
    console = Console(file=sys.stderr, force_terminal=force_color, color_system="standard" if force_color else None)
    handler = RichHandler(
        console=console,
        level=console_level,
        show_time=True,
        log_time_format="%d/%m-%H:%M",
        show_path=False,
        markup=False,
        rich_tracebacks=True,
    )
    logger.addHandler(handler)

    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        log_path = log_dir / f"mrsiprep_{timestamp}.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%d/%m-%H:%M"))
        logger.addHandler(file_handler)
        logger.info("Logging to %s", log_path)
    return logger


LOGGER = logging.getLogger("mrsiprep")

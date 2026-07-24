"""Workflow base helpers."""

from __future__ import annotations

from pathlib import Path


def ensure_work_dirs(config) -> None:
    """Create the derivatives and work directories if they don't already exist.

    :param config: Run-wide config exposing ``derivative_dir`` and ``work_dir``.
    """
    config.derivative_dir.mkdir(parents=True, exist_ok=True)
    Path(config.work_dir).mkdir(parents=True, exist_ok=True)

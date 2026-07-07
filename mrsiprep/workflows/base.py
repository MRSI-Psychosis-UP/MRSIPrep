"""Workflow base helpers."""

from __future__ import annotations

from pathlib import Path


def ensure_work_dirs(config) -> None:
    config.derivative_dir.mkdir(parents=True, exist_ok=True)
    Path(config.work_dir).mkdir(parents=True, exist_ok=True)

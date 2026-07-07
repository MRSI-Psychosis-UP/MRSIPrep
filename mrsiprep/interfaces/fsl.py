"""FSL interface helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

from mrsiprep.utils.subprocess_utils import run_checked


class FSLError(RuntimeError):
    """Raised when FSL cannot complete a requested operation."""


def require(command: str) -> str:
    path = shutil.which(command)
    if not path:
        raise FSLError(f"Required FSL command not found on PATH: {command}")
    return path


def run_fast(t1_path: str | Path, out_prefix: str | Path, verbose: bool = False) -> dict[str, Path]:
    require("fast")
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["fast", "-t", "1", "-n", "3", "-H", "0.1", "-I", "4", "-l", "20.0", "-o", str(out_prefix), str(t1_path)]
    run_checked(cmd, verbose=verbose, error_cls=FSLError, error_prefix="fast")
    return {
        "CSF": out_prefix.parent / f"{out_prefix.name}_pve_0.nii.gz",
        "GM": out_prefix.parent / f"{out_prefix.name}_pve_1.nii.gz",
        "WM": out_prefix.parent / f"{out_prefix.name}_pve_2.nii.gz",
    }

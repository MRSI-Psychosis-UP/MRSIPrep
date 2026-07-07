"""FreeSurfer helpers."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from mrsiprep.utils.misc import format_elapsed_hm
from mrsiprep.utils.subprocess_utils import run_checked


class FreeSurferError(RuntimeError):
    """Raised for FreeSurfer-related failures."""


def check_license() -> None:
    import os

    candidates = []
    if os.environ.get("FS_LICENSE"):
        candidates.append(Path(os.environ["FS_LICENSE"]))
    if os.environ.get("FREESURFER_HOME"):
        candidates.append(Path(os.environ["FREESURFER_HOME"]) / "license.txt")
    candidates.append(Path("/opt/freesurfer/license.txt"))
    for license_path in candidates:
        if license_path.exists():
            os.environ["FS_LICENSE"] = str(license_path)
            return
    raise FreeSurferError("FreeSurfer license not found. Set FS_LICENSE to use FreeSurfer/Chimera mode.")


def require_command(command: str) -> str:
    path = shutil.which(command)
    if not path:
        raise FreeSurferError(f"{command} command not found on PATH.")
    return path


def freesurfer_subject_id(t1_path: str | Path) -> str:
    path = Path(t1_path)
    name = path.name
    if name.endswith(".nii.gz"):
        stem = name[:-7]
    elif name.endswith(".mgz"):
        stem = name[:-4]
    else:
        stem = path.stem
    # Chimera derives its expected FreeSurfer subject ID by stripping only the
    # final BIDS entity (the suffix, e.g. "T1w") from the filename, so the
    # recon-all subject directory must match that convention exactly.
    return stem.rsplit("_", 1)[0] if "_" in stem else stem


def subject_dir_valid(fs_subjects_dir: str | Path, subject: str) -> bool:
    root = Path(fs_subjects_dir) / subject
    required = [
        root / "mri" / "brain.mgz",
        root / "mri" / "aseg.mgz",
        root / "mri" / "orig.mgz",
        root / "surf" / "lh.white",
        root / "surf" / "rh.white",
        root / "surf" / "lh.pial",
        root / "surf" / "rh.pial",
    ]
    return all(path.exists() for path in required)


def run_recon_all(t1_path: str | Path, fs_subjects_dir: str | Path, subject: str, force: bool = False, nthreads: int = 4, verbose: bool = False, debug=None) -> Path:
    require_command("recon-all")
    check_license()
    fs_subjects_dir = Path(fs_subjects_dir)
    subject_root = fs_subjects_dir / subject
    if force and subject_root.exists():
        shutil.rmtree(subject_root)
    if subject_dir_valid(fs_subjects_dir, subject) and not force:
        if debug is not None:
            debug.info(f"recon-all: reusing existing output for {subject}")
        return subject_root
    fs_subjects_dir.mkdir(parents=True, exist_ok=True)
    if subject_root.exists() and not force:
        cmd = ["recon-all", "-s", subject, "-all", "-sd", str(fs_subjects_dir), "-openmp", str(nthreads)]
    else:
        cmd = ["recon-all", "-s", subject, "-i", str(t1_path), "-all", "-sd", str(fs_subjects_dir), "-openmp", str(nthreads)]
    if debug is not None:
        debug.info(f"recon-all: starting -all reconstruction for {subject} ({nthreads} threads, this can take 1-3 hours)")
    start = time.monotonic()
    run_checked(cmd, verbose=verbose, error_cls=FreeSurferError, error_prefix="recon-all")
    if not subject_dir_valid(fs_subjects_dir, subject):
        raise FreeSurferError(
            f"recon-all finished but required outputs are missing for {subject}: "
            f"{fs_subjects_dir / subject}"
        )
    if debug is not None:
        debug.info(f"recon-all: finished for {subject} in {format_elapsed_hm(time.monotonic() - start)}")
    return fs_subjects_dir / subject

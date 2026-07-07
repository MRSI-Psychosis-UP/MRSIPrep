"""Chimera parcellation wrapper."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from mrsiprep.utils.subprocess_utils import run_checked


class ChimeraError(RuntimeError):
    """Raised when Chimera parcellation cannot be created."""


def check_chimera() -> None:
    if not shutil.which("chimera"):
        raise ChimeraError("Chimera command not found on PATH.")


def run_chimera(
    bids_dir: str | Path,
    derivatives_dir: str | Path,
    fs_subjects_dir: str | Path,
    t1_path: str | Path,
    subject: str,
    session: str | None,
    scheme: str,
    scale: int,
    grow: int,
    verbose: bool = False,
    milestones: bool = False,
    force: bool = False,
    debug=None,
) -> Path:
    check_chimera()
    derivatives_dir = Path(derivatives_dir)
    ids_line = f"{Path(t1_path).name}\n"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        handle.write(ids_line)
        ids_path = Path(handle.name)
    try:
        cmd = [
            "chimera",
            "-b",
            str(bids_dir),
            "-d",
            str(derivatives_dir),
            "--freesurferdir",
            str(fs_subjects_dir),
            "-p",
            scheme,
            "-g",
            str(grow),
            "-s",
            str(scale),
            "-ids",
            str(ids_path),
            # Chimera's own --nthreads dispatches subjects to a
            # ThreadPoolExecutor whose futures are never awaited (chimera.py
            # main(), the parallel branch of chimera_parcellation): with
            # nthreads > 1 it reports "Finished" and returns immediately,
            # silently dropping exceptions and any unfinished work. Forcing
            # nthreads=1 here makes chimera run synchronously so failures
            # surface and outputs are actually written before we look for
            # them below. The caller's --nthreads still governs recon-all.
            "--nthreads",
            "1",
        ]
        if force:
            # chimera's CLI parses --force into args.force but main() never
            # passes it down to chimera_parcellation()/build_parcellation()
            # (confirmed in chimera-brainparcellation 0.3.1) - the flag is a
            # silent no-op. Deleting prior output ourselves is the only way
            # to make chimera's own existence-check see stale results as
            # missing and actually recompute.
            cmd.append("--force")
            pattern = f"sub-{subject}"
            if session:
                pattern += f"_ses-{session}"
            for stale in (derivatives_dir / "chimera").rglob(f"{pattern}*atlas-chimera{scheme}*scale-{scale}*"):
                stale.unlink(missing_ok=True)
        if debug is not None:
            debug.info(f"chimera: starting scheme={scheme} scale={scale} grow={grow}mm (single-threaded; this can take 10-20+ minutes)")
            debug.debug(f"chimera: command: {' '.join(cmd)}")
        env = None
        if milestones:
            env = os.environ.copy()
            env["CHIMERA_MILESTONES"] = "1"
        # Milestones are only visible if chimera's own stdout streams live;
        # mrsiprep's milestone patch (docker/patch_chimera_milestones.py)
        # prints "[chimera-milestone] ..." lines that would otherwise sit
        # captured in the buffer until the subprocess exits.
        result = run_checked(cmd, verbose=verbose or milestones, merge_stderr=True, env=env, error_cls=ChimeraError, error_prefix="chimera")
        if debug is not None:
            debug.info("chimera: subprocess finished, locating output parcellation")
    finally:
        ids_path.unlink(missing_ok=True)
    pattern = f"sub-{subject}"
    if session:
        pattern += f"_ses-{session}"
    glob_pattern = f"{pattern}*atlas-chimera{scheme}*scale-{scale}*_dseg.nii*"
    if debug is not None:
        debug.debug(f"chimera: searching {derivatives_dir / 'chimera'} for {glob_pattern}")
    candidates = sorted((derivatives_dir / "chimera").rglob(glob_pattern))
    if not candidates:
        output = f"\n{result.stdout}" if result.stdout else ""
        raise ChimeraError(f"Chimera completed but expected parcellation was not found.{output}")
    if debug is not None:
        debug.info(f"chimera: found output {candidates[0]}")
    return candidates[0]

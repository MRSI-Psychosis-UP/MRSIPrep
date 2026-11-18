"""Chimera parcellation wrapper."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

from mrsiprep.utils.subprocess_utils import run_checked


class ChimeraError(RuntimeError):
    """Raised when Chimera parcellation cannot be created."""


def check_chimera() -> None:
    if not shutil.which("chimera"):
        raise ChimeraError("Chimera command not found on PATH.")


def _as_list(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _scale_matches(name: str, scale: int) -> bool:
    """Whether a Chimera output filename belongs to `scale`.

    Chimera folds the scale into the desc entity as ``desc-scale3grow2mm``,
    but other builds/atlases spell it ``scale-3``; accept either. The trailing
    negative lookahead keeps ``scale3`` from also matching ``scale30``.
    """
    return re.search(rf"scale-?{scale}(?!\d)", name) is not None


def _grow_matches(name: str, grow: int) -> bool:
    """Whether a Chimera output filename belongs to `grow` mm.

    Chimera writes ``grow2mm`` into the desc entity, but omits the marker
    entirely for ``grow=0`` (its ``if growwm[ngrow] == "0"`` branch). A name
    carrying no marker therefore can't be attributed to a particular growth,
    so it is treated as neutral (matching whatever was asked for) rather than
    excluded -- being strict here would drop otherwise-valid outputs. Names
    that *do* carry a marker are filtered on it, which is what keeps several
    requested grow distances from collapsing onto one result.
    """
    if not re.search(r"grow\d+mm", name):
        return True
    return re.search(rf"grow{grow}mm", name) is not None


def run_chimera(
    bids_dir: str | Path,
    derivatives_dir: str | Path,
    fs_subjects_dir: str | Path,
    t1_path: str | Path,
    subject: str,
    session: str | None,
    scheme: str | Sequence[str],
    scale: int | Sequence[int],
    grow: int | Sequence[int],
    verbose: bool = False,
    milestones: bool = False,
    force: bool = False,
    debug=None,
) -> list[tuple[str, int, int, Path]]:
    """Run Chimera once, building every requested scheme x scale x grow parcellation.

    Chimera's own CLI splits ``--parcodes``/``--scale``/``--growwm`` on commas
    and cross-products them internally, so passing the full lists through
    costs a single invocation (and a single recon-all) rather than one per
    combination.

    :returns: ``[(scheme, scale, grow, dseg_path), ...]`` for the combinations
        that actually produced output. This can be shorter than the nominal
        cross product: ``--scale`` only applies to multi-resolution
        parcellations (Lausanne ``L`` cortex), so a non-``L`` scheme yields one
        result no matter how many scales were requested.
    :raises ChimeraError: If Chimera produced no parcellation at all.
    """
    check_chimera()
    schemes = _as_list(scheme)
    scales = _as_list(scale)
    grows = _as_list(grow)
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
            ",".join(str(item) for item in schemes),
            "-g",
            ",".join(str(item) for item in grows),
            "-s",
            ",".join(str(item) for item in scales),
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
            for one_scheme in schemes:
                for one_scale in scales:
                    for stale in (derivatives_dir / "chimera").rglob(
                        f"{pattern}*atlas-chimera{one_scheme}*scale-{one_scale}*"
                    ):
                        stale.unlink(missing_ok=True)
        if debug is not None:
            debug.info(
                f"chimera: starting schemes={','.join(str(s) for s in schemes)} "
                f"scales={','.join(str(s) for s in scales)} grow={','.join(str(g) for g in grows)}mm "
                "(single-threaded; this can take 10-20+ minutes)"
            )
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
    found: list[tuple[str, int, int, Path]] = []
    missing: list[str] = []
    for one_scheme in schemes:
        glob_pattern = f"{pattern}*atlas-chimera{one_scheme}*_dseg.nii*"
        if debug is not None:
            debug.debug(f"chimera: searching {derivatives_dir / 'chimera'} for {glob_pattern}")
        candidates = sorted((derivatives_dir / "chimera").rglob(glob_pattern))
        scheme_hits = 0
        for one_scale in scales:
            for one_grow in grows:
                match = next(
                    (
                        path
                        for path in candidates
                        if _scale_matches(path.name, one_scale) and _grow_matches(path.name, one_grow)
                    ),
                    None,
                )
                if match is not None:
                    found.append((one_scheme, one_scale, one_grow, match))
                    scheme_hits += 1
                    if debug is not None:
                        debug.info(f"chimera: found output {match}")
                else:
                    missing.append(f"{one_scheme}@scale{one_scale}grow{one_grow}mm")
        if scheme_hits == 0 and candidates:
            # Scheme produced output but matched no scale: its cortex
            # parcellation isn't multi-resolution, so the single result is
            # scale-independent. Attribute it to the first requested
            # scale/grow rather than dropping it.
            found.append((one_scheme, scales[0], grows[0], candidates[0]))
            missing = [item for item in missing if not item.startswith(f"{one_scheme}@")]
            if debug is not None:
                debug.info(f"chimera: found scale-independent output {candidates[0]}")
    if not found:
        output = f"\n{result.stdout}" if result.stdout else ""
        raise ChimeraError(f"Chimera completed but expected parcellation was not found.{output}")
    if missing and debug is not None:
        debug.warning(f"chimera: no output for {', '.join(missing)} (scheme may not support that scale)")
    return found

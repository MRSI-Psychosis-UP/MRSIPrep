"""MRSI preprocessing workflow."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from mrsiprep.io.loaders import MRSIInputs
from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.mrsi.filtering import filter_metabolite_maps
from mrsiprep.mrsi.masks import ensure_brainmask
from mrsiprep.mrsi.quality import make_quality_masks
from mrsiprep.mrsi.reference import generate_reference


@dataclass
class MRSIResult:
    raw_maps: dict[str, Path]
    preproc_maps: dict[str, Path]
    corrected_maps: dict[str, Path]
    crlb_maps: dict[str, Path]
    snr_map: Path | None
    linewidth_map: Path | None
    water_map: Path | None
    brainmask: Path
    reference: Path
    qcmasks: dict[str, Path]
    qc_summary: Path


def _same_file(a: Path, b: Path) -> bool:
    """True when `a` and `b` are the same underlying file, even if reached
    through different (e.g. separately bind-mounted) paths."""
    try:
        return a.samefile(b)
    except OSError:
        return False


def _copy_native_maps(config, subject: str, session: str | None, inputs: MRSIInputs) -> None:
    """Copy (not symlink) raw/quality maps into the mrsi/orig derivatives tree.

    A symlink written from inside a container would encode a path relative
    to the container's own mount layout (e.g. separate `/data` and `/out`
    bind mounts), which has no reliable relationship to the host filesystem
    outside the container -- the link would dangle there even though the
    source file exists. Copying these small maps avoids that.
    """
    links: list[tuple[Path | None, dict, str]] = [
        (inputs.snr_map, {"desc": "snr"}, "orig"),
        (inputs.linewidth_map, {"desc": "fwhm"}, "orig"),
    ]
    for met, path in inputs.crlb_maps.items():
        links.append((path, {"met": met, "desc": "crlb"}, "orig"))
    for met, path in inputs.metabolite_maps.items():
        links.append((path, {"met": met, "desc": "signal"}, "mrsi"))
    for source, entities, space in links:
        if source is None or not source.exists():
            continue
        target = mrsi_derivative(config.derivative_dir, subject, session, space=space, suffix_override="mrsi", **entities)
        if target.exists() and _same_file(source, target):
            # BIDSLayout's mrsi-<space> fallback (see
            # BIDSLayout._mrsi_input_roots) can read raw inputs straight out
            # of mrsiprep's own output tree (mrsi/<space>/) when no separate
            # mrsi-<space> derivatives root exists -- in that case source and
            # target are the same file, and unlinking it before copying would
            # destroy the only copy. Comparing resolved path strings alone is
            # not enough to detect this: the BIDS root and derivatives root
            # are commonly two *separate* Docker bind mounts (e.g. /data and
            # /out) that both happen to point at the same underlying host
            # file, so their in-container resolved paths differ even though
            # they're the same file -- inode identity (samefile) survives
            # that, so it's checked instead/first.
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        try:
            shutil.copy2(source, tmp_target)
        except FileNotFoundError:
            # Source vanished between the exists() check above and the copy
            # (e.g. concurrent regeneration of the input dataset) -- this is
            # an optional/QC-only map, so skip it rather than fail the whole
            # recording.
            tmp_target.unlink(missing_ok=True)
            continue
        except BaseException:
            # Covers KeyboardInterrupt/SIGTERM landing mid-copy too: the
            # partial file is the scratch tmp_target, never the real target,
            # so the existing (or absent) target is left exactly as it was.
            tmp_target.unlink(missing_ok=True)
            raise
        # Atomic on POSIX (same filesystem, since tmp_target sits next to
        # target): either the old target survives untouched or the new one
        # lands complete -- no window where target is missing or truncated,
        # even if a signal arrives right at this line.
        os.replace(tmp_target, target)


def run_mrsi_workflow(config, subject: str, session: str | None, inputs: MRSIInputs) -> MRSIResult:
    _copy_native_maps(config, subject, session, inputs)
    brainmask = ensure_brainmask(config, subject, session, inputs.brainmask, inputs.water_map, inputs.metabolite_maps)
    preproc = filter_metabolite_maps(config, subject, session, inputs.metabolite_maps, brainmask)
    reference = generate_reference(config, subject, session, preproc, preferred_met=config.ref_met)
    qcmasks, qc_summary = make_quality_masks(
        config,
        subject,
        session,
        preproc,
        inputs.crlb_maps,
        inputs.snr_map,
        inputs.linewidth_map,
        brainmask,
    )
    return MRSIResult(
        raw_maps=inputs.metabolite_maps,
        preproc_maps=preproc,
        corrected_maps=preproc,
        crlb_maps=inputs.crlb_maps,
        snr_map=inputs.snr_map,
        linewidth_map=inputs.linewidth_map,
        water_map=inputs.water_map,
        brainmask=brainmask,
        reference=reference,
        qcmasks=qcmasks,
        qc_summary=qc_summary,
    )

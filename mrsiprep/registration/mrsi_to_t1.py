"""MRSI-to-T1 registration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.interfaces.ants import register
from mrsiprep.registration.transforms import all_exist, ants_transform_prefix, transform_paths


@dataclass
class MRSIToT1Result:
    forward: list[Path]
    inverse: list[Path]
    prefix: Path


def run_mrsi_to_t1(config, subject: str, session: str | None, mrsi_reference: Path, t1_path: Path, fixed_mask: Path | None = None) -> MRSIToT1Result:
    prefix = ants_transform_prefix(config.derivative_dir, subject, session, "mrsi")
    forward = transform_paths(prefix, "forward")
    inverse = transform_paths(prefix, "inverse")
    if all_exist(forward) and all_exist(inverse) and not (config.overwrite_t1_reg or config.overwrite):
        return MRSIToT1Result(forward, inverse, prefix)
    register(t1_path, mrsi_reference, prefix, transform="sr", fixed_mask=fixed_mask, verbose=config.verbose >= 3, threads=config.nthreads)
    return MRSIToT1Result(transform_paths(prefix, "forward"), transform_paths(prefix, "inverse"), prefix)

"""MRSI-to-T1 registration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.interfaces.ants import register
from mrsiprep.interfaces.fsl import register_flirt
from mrsiprep.registration.transforms import all_exist, ants_transform_prefix, transform_paths


@dataclass
class MRSIToT1Result:
    forward: list[Path]
    inverse: list[Path]
    prefix: Path


def run_mrsi_to_t1(config, subject: str, session: str | None, mrsi_reference: Path, t1_path: Path, fixed_mask: Path | None = None) -> MRSIToT1Result:
    backend = config.registration_backend
    prefix = ants_transform_prefix(config.derivative_dir, subject, session, "mrsi", backend=backend)
    forward = transform_paths(prefix, "forward", backend=backend)
    inverse = transform_paths(prefix, "inverse", backend=backend)
    if all_exist(forward) and all_exist(inverse) and not (config.overwrite_t1_reg or config.overwrite):
        return MRSIToT1Result(forward, inverse, prefix)
    if backend == "fsl":
        # FLIRT-only backend: affine, no deformable stage (see interfaces/fsl.py).
        register_flirt(
            t1_path,
            mrsi_reference,
            prefix,
            fixed_mask=fixed_mask,
            flirt_dof=config.fsl_mrsi_to_t1_dof,
            flirt_cost=config.fsl_cost,
            flirt_init=config.fsl_mrsi_to_t1_init,
            verbose=config.verbose >= 3,
        )
    else:
        register(
            t1_path,
            mrsi_reference,
            prefix,
            transform=config.ants_mrsi_to_t1_transform,
            fixed_mask=fixed_mask,
            verbose=config.verbose >= 3,
            threads=config.nthreads,
        )
    return MRSIToT1Result(
        transform_paths(prefix, "forward", backend=backend, include_missing=False),
        transform_paths(prefix, "inverse", backend=backend, include_missing=False),
        prefix,
    )


def run_mrsi_to_t1_rigid_mi(config, subject: str, session: str | None, mrsi_reference: Path, t1_path: Path, fixed_mask: Path | None = None) -> MRSIToT1Result:
    """MIDAS-faithful MRSI<->T1 registration: rigid-only, mutual-information
    driven (Maudsley et al. 2006, 'Image registration' section). Uses ANTs'
    ``Rigid`` preset (or, for the fsl backend, 6-DOF FLIRT) instead of the
    default path's higher-DOF registration, so no nonlinear warp is estimated
    between MRSI and T1 -- the forward/inverse transforms are the rigid affine
    only.
    """
    backend = config.registration_backend
    prefix = ants_transform_prefix(config.derivative_dir, subject, session, "mrsi", backend=backend)
    forward = transform_paths(prefix, "forward", backend=backend)
    inverse = transform_paths(prefix, "inverse", backend=backend)
    if all_exist(forward) and all_exist(inverse) and not (config.overwrite_t1_reg or config.overwrite):
        return MRSIToT1Result(forward, inverse, prefix)
    if backend == "fsl":
        register_flirt(
            t1_path,
            mrsi_reference,
            prefix,
            fixed_mask=fixed_mask,
            flirt_dof=6,
            flirt_cost=config.fsl_cost,
            flirt_init=config.fsl_mrsi_to_t1_init,
            verbose=config.verbose >= 3,
        )
    else:
        register(t1_path, mrsi_reference, prefix, transform="Rigid", fixed_mask=fixed_mask, verbose=config.verbose >= 3, threads=config.nthreads)
    return MRSIToT1Result(
        transform_paths(prefix, "forward", backend=backend, include_missing=False),
        transform_paths(prefix, "inverse", backend=backend, include_missing=False),
        prefix,
    )

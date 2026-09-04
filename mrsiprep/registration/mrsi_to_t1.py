"""MRSI-to-T1 registration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.utils.debug import note_cache_hit, note_computed
from mrsiprep.interfaces.ants import register
from mrsiprep.interfaces.fsl import default_fnirt_warpres, register_fnirt, register_flirt
from mrsiprep.registration.transforms import all_exist, ants_transform_prefix, transform_paths


@dataclass
class MRSIToT1Result:
    forward: list[Path]
    inverse: list[Path]
    prefix: Path


def run_mrsi_to_t1(
    config,
    subject: str,
    session: str | None,
    mrsi_reference: Path,
    t1_path: Path,
    fixed_mask: Path | None = None,
    moving_mask: Path | None = None,
) -> MRSIToT1Result:
    backend = config.registration_backend
    deformable = backend == "fsl" and getattr(config, "fsl_deformable", False)
    prefix = ants_transform_prefix(config.derivative_dir, subject, session, "mrsi", backend=backend)
    forward = transform_paths(prefix, "forward", backend=backend, deformable=deformable)
    inverse = transform_paths(prefix, "inverse", backend=backend, deformable=deformable)
    if all_exist(forward) and all_exist(inverse) and not (config.overwrite_t1_reg or config.overwrite):
        note_cache_hit()
        return MRSIToT1Result(forward, inverse, prefix)
    note_computed()
    if backend == "fsl" and deformable:
        if moving_mask is None:
            raise ValueError("--fsl-deformable (FNIRT) requires an MRSI brainmask (moving_mask) but none was provided.")
        warpres = config.fsl_fnirt_warpres or default_fnirt_warpres(_voxel_size_mm(mrsi_reference))
        register_fnirt(
            t1_path,
            mrsi_reference,
            prefix,
            fixed_mask=fixed_mask,
            moving_mask=moving_mask,
            flirt_dof=config.fsl_mrsi_to_t1_dof,
            flirt_cost=config.fsl_cost,
            warpres=warpres,
            lambda_weight=config.fsl_fnirt_lambda,
            verbose=config.verbose >= 3,
        )
    elif backend == "fsl":
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
        transform_paths(prefix, "forward", backend=backend, include_missing=False, deformable=deformable),
        transform_paths(prefix, "inverse", backend=backend, include_missing=False, deformable=deformable),
        prefix,
    )


def _voxel_size_mm(image_path: Path) -> tuple[float, float, float]:
    import nibabel as nib

    zooms = nib.load(str(image_path)).header.get_zooms()[:3]
    return tuple(float(value) for value in zooms)



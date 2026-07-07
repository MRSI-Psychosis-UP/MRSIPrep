"""T1-to-MNI registration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.interfaces.ants import register
from mrsiprep.registration.transforms import all_exist, ants_transform_prefix, transform_paths
from mrsiprep.utils.images import resolve_mni_resolution


@dataclass
class T1ToMNIResult:
    forward: list[Path]
    inverse: list[Path]
    prefix: Path
    template: object


def run_t1_to_mni(config, subject: str, session: str | None, t1_path: Path, mrsi_reference: Path | None = None) -> T1ToMNIResult:
    from nilearn import datasets

    prefix = ants_transform_prefix(config.derivative_dir, subject, session, "anat")
    forward = transform_paths(prefix, "forward")
    inverse = transform_paths(prefix, "inverse")
    resolution = resolve_mni_resolution(config.mni_resolution, t1_path, mrsi_reference)
    template = datasets.load_mni152_template(resolution)
    if all_exist(forward) and all_exist(inverse) and not (config.overwrite_mni_reg or config.overwrite):
        return T1ToMNIResult(forward, inverse, prefix, template)
    if config.normalization == "existing":
        raise FileNotFoundError(
            f"--normalization existing requires precomputed T1-to-MNI transforms at {prefix} "
            f"(.syn.nii.gz/.affine.mat/.syn_inv.nii.gz/.affine_inv.mat), but they were not found."
        )
    register(template, t1_path, prefix, transform="s", verbose=config.verbose >= 3, threads=config.nthreads)
    return T1ToMNIResult(transform_paths(prefix, "forward"), transform_paths(prefix, "inverse"), prefix, template)

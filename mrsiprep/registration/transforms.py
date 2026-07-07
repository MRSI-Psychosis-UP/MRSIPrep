"""Transform path and application helpers."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.interfaces.ants import apply_transforms
from mrsiprep.utils.misc import normalize_session, normalize_subject


def ants_transform_prefix(root: Path, subject: str, session: str | None, stage: str) -> Path:
    sub = f"sub-{normalize_subject(subject)}"
    ses = f"ses-{normalize_session(session)}" if session else "ses-none"
    if stage == "mrsi":
        return root / sub / ses / "transforms" / "mrsi" / f"{sub}_{ses}_desc-mrsi_to_t1w"
    if stage == "anat":
        return root / sub / ses / "transforms" / "anat" / f"{sub}_{ses}_desc-t1w_to_mni"
    if stage == "t1-template":
        return root / sub / ses / "transforms" / "anat" / f"{sub}_{ses}_desc-t1w_to_template"
    if stage == "template-mni":
        return root / sub / "ses-all" / "transforms" / "anat" / f"{sub}_ses-all_desc-template_to_mni"
    raise ValueError(f"Unsupported transform stage: {stage}")


def transform_paths(prefix: Path, direction: str = "forward", include_missing: bool = True) -> list[Path]:
    if direction == "forward":
        paths = [prefix.with_suffix(".syn.nii.gz"), prefix.with_suffix(".affine.mat")]
    elif direction == "inverse":
        paths = [prefix.with_suffix(".affine_inv.mat"), prefix.with_suffix(".syn_inv.nii.gz")]
    else:
        raise ValueError(f"Unsupported direction: {direction}")
    return paths if include_missing else [path for path in paths if path.exists()]


def all_exist(paths: list[Path]) -> bool:
    return bool(paths) and all(path.exists() for path in paths)


def apply_image_transform(fixed, moving, transforms: list[Path], out_path: Path, interpolation: str = "linear", threads: int | None = None) -> Path:
    return apply_transforms(fixed, moving, transforms, out_path, interpolation=interpolation, threads=threads)

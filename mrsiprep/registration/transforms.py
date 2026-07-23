"""Transform path and application helpers."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.utils.misc import normalize_session, normalize_subject


def ants_transform_prefix(root: Path, subject: str, session: str | None, stage: str, backend: str = "ants") -> Path:
    """Transform-file prefix for a given pipeline stage and registration backend.

    ``backend`` is baked into the prefix (as a ``desc`` suffix, e.g.
    ``..._desc-mrsi_to_t1w`` for ants vs ``..._desc-mrsi_to_t1w_fsl`` for fsl) so
    that switching ``--registration-backend`` between runs of the same
    subject/session can never resolve to, and silently reuse, a transform file
    written by the *other* backend -- the two backends' derivatives live at
    distinct paths, not just distinct suffixes on a shared path.
    """
    sub = f"sub-{normalize_subject(subject)}"
    ses = f"ses-{normalize_session(session)}" if session else "ses-none"
    backend_suffix = "" if backend == "ants" else f"_{backend}"
    if stage == "mrsi":
        return root / sub / ses / "transforms" / "mrsi" / f"{sub}_{ses}_desc-mrsi_to_t1w{backend_suffix}"
    if stage == "anat":
        return root / sub / ses / "transforms" / "anat" / f"{sub}_{ses}_desc-t1w_to_mni{backend_suffix}"
    if stage == "t1-template":
        return root / sub / ses / "transforms" / "anat" / f"{sub}_{ses}_desc-t1w_to_template{backend_suffix}"
    if stage == "template-mni":
        return root / sub / "ses-all" / "transforms" / "anat" / f"{sub}_ses-all_desc-template_to_mni{backend_suffix}"
    raise ValueError(f"Unsupported transform stage: {stage}")


def transform_paths(prefix: Path, direction: str = "forward", include_missing: bool = True, backend: str = "ants", deformable: bool = False) -> list[Path]:
    if backend == "ants":
        if direction == "forward":
            paths = [prefix.with_suffix(".syn.nii.gz"), prefix.with_suffix(".affine.mat")]
        elif direction == "inverse":
            paths = [prefix.with_suffix(".affine_inv.mat"), prefix.with_suffix(".syn_inv.nii.gz")]
        else:
            raise ValueError(f"Unsupported direction: {direction}")
    elif backend == "fsl":
        # FLIRT-only: a single affine per direction. flirt+FNIRT (deformable):
        # warp + affine per direction -- apply_transforms() prefers the warp
        # (it already encodes the affine, see interfaces.fsl.register_fnirt)
        # and ignores the affine entry when both are present, but both are
        # listed here so all_exist()/existence checks see the full set of
        # files this registration actually produced.
        if direction == "forward":
            paths = [prefix.with_suffix(".flirt.mat")]
            if deformable:
                paths = [prefix.with_suffix(".fnirt_warp.nii.gz"), *paths]
        elif direction == "inverse":
            paths = [prefix.with_suffix(".flirt_inv.mat")]
            if deformable:
                paths = [*paths, prefix.with_suffix(".fnirt_warp_inv.nii.gz")]
        else:
            raise ValueError(f"Unsupported direction: {direction}")
    else:
        raise ValueError(f"Unsupported registration backend: {backend}")
    return paths if include_missing else [path for path in paths if path.exists()]


def all_exist(paths: list[Path]) -> bool:
    return bool(paths) and all(path.exists() for path in paths)


def apply_image_transform(fixed, moving, transforms: list[Path], out_path: Path, interpolation: str = "linear", threads: int | None = None) -> Path:
    if any(_is_fsl_transform(Path(path)) for path in transforms):
        from mrsiprep.interfaces.fsl import apply_transforms

        return apply_transforms(fixed, moving, transforms, out_path, interpolation=interpolation)
    from mrsiprep.interfaces.ants import apply_transforms

    return apply_transforms(fixed, moving, transforms, out_path, interpolation=interpolation, threads=threads)


_FSL_TRANSFORM_SUFFIXES = (".flirt.mat", ".flirt_inv.mat", ".fnirt_warp.nii.gz", ".fnirt_warp_inv.nii.gz")


def _is_fsl_transform(path: Path) -> bool:
    """FSL (FLIRT/FNIRT) transform files use distinct suffixes
    (``.flirt.mat``/``.flirt_inv.mat``/``.fnirt_warp.nii.gz``/
    ``.fnirt_warp_inv.nii.gz``) from ANTs' ``.affine.mat``/``.syn.nii.gz``/
    etc., so this is an unambiguous filename check, not content-sniffing."""
    return path.name.endswith(_FSL_TRANSFORM_SUFFIXES)

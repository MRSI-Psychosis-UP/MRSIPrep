"""ANTs/antspyx interface."""

from __future__ import annotations

import shutil
import tempfile
import time
import os
from contextlib import contextmanager
from pathlib import Path

import nibabel as nib

from mrsiprep.utils.subprocess_utils import run_checked


class ANTsError(RuntimeError):
    """Raised when ANTs cannot complete a requested operation."""


def _import_ants():
    try:
        import ants  # type: ignore
    except Exception as exc:
        raise ANTsError("antspyx is required for this operation. Install mrsiprep[ants] or provide existing transforms.") from exc
    required = ("image_read", "registration", "apply_transforms")
    if not all(hasattr(ants, name) for name in required):
        raise ANTsError(
            "The installed 'ants' module is not antspyx or is incomplete. "
            "Install antspyx, or use the ANTs CLI-backed registration path."
        )
    return ants


def _load_ants_image(image):
    ants = _import_ants()
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.exists():
            raise ANTsError(f"Image path does not exist: {path}")
        return ants.image_read(str(path))
    if isinstance(image, nib.Nifti1Image):
        with tempfile.NamedTemporaryFile(suffix=".nii.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            nib.save(image, str(tmp_path))
            return ants.image_read(str(tmp_path))
        finally:
            tmp_path.unlink(missing_ok=True)
    if image.__class__.__name__ == "ANTsImage":
        return image
    raise ANTsError("Image must be a path, nibabel image, or ANTsImage.")


@contextmanager
def _itk_thread_env(threads: int | None):
    if threads is None:
        yield
        return
    previous = os.environ.get("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS")
    os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = str(max(1, int(threads)))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", None)
        else:
            os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = previous


def register(
    fixed,
    moving,
    out_prefix: str | Path,
    transform: str = "sr",
    fixed_mask=None,
    moving_mask=None,
    verbose: bool = False,
    threads: int | None = None,
) -> dict:
    try:
        ants = _import_ants()
        fixed_img = _load_ants_image(fixed)
        moving_img = _load_ants_image(moving)
        fixed_mask_img = _load_ants_image(fixed_mask) if fixed_mask is not None else None
        moving_mask_img = _load_ants_image(moving_mask) if moving_mask is not None else None
        with _itk_thread_env(threads):
            tx = ants.registration(
                fixed=fixed_img,
                moving=moving_img,
                fixed_mask=fixed_mask_img,
                moving_mask=moving_mask_img,
                type_of_transform=f"antsRegistrationSyN[{transform}]",
                verbose=verbose,
            )
        return save_all_transforms(tx, out_prefix)
    except ANTsError:
        return register_cli(fixed, moving, out_prefix, transform=transform, fixed_mask=fixed_mask, verbose=verbose, threads=threads)


def save_all_transforms(ants_tx: dict, out_prefix: str | Path) -> dict[str, list[Path]]:
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    outputs = {"forward": [], "inverse": []}
    for path in ants_tx.get("fwdtransforms", []):
        path = Path(path)
        if "Warp" in path.name:
            out = out_prefix.with_suffix(".syn.nii.gz")
        elif "Affine" in path.name:
            out = out_prefix.with_suffix(".affine.mat")
        else:
            out = out_prefix.parent / f"{out_prefix.name}.{path.name}"
        shutil.copy2(path, out)
        outputs["forward"].append(out)
    for path in ants_tx.get("invtransforms", []):
        path = Path(path)
        if "InverseWarp" in path.name or "Warp" in path.name:
            out = out_prefix.with_suffix(".syn_inv.nii.gz")
        elif "Affine" in path.name:
            out = out_prefix.with_suffix(".affine_inv.mat")
        else:
            out = out_prefix.parent / f"{out_prefix.name}.{path.name}"
        shutil.copy2(path, out)
        outputs["inverse"].append(out)
    return outputs


def apply_transforms(
    fixed,
    moving,
    transforms: list[str | Path],
    out_path: str | Path | None = None,
    interpolation: str = "linear",
    threads: int | None = None,
):
    try:
        ants = _import_ants()
        existing = [str(Path(path)) for path in transforms if Path(path).exists()]
        if not existing:
            raise ANTsError(f"No transform files exist in list: {transforms}")
        fixed_img = _load_ants_image(fixed)
        moving_img = _load_ants_image(moving)
        with _itk_thread_env(threads):
            warped = ants.apply_transforms(fixed=fixed_img, moving=moving_img, transformlist=existing, interpolator=interpolation)
        if out_path is None:
            return warped
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ants.image_write(warped, str(out_path))
        return out_path
    except ANTsError:
        if out_path is None:
            raise ANTsError("ANTs CLI fallback requires an output path.")
        return apply_transforms_cli(fixed, moving, transforms, out_path, interpolation=interpolation, threads=threads)


class Registration:
    """Small ANTs registration facade matching the mrsitoolbox workflow API."""

    def register(
        self,
        fixed_input,
        moving_input,
        fixed_mask=None,
        moving_mask=None,
        transform: str = "sr",
        verbose: bool = False,
        threads: int | None = None,
    ):
        ants = _import_ants()
        fixed_image = _load_ants_image(fixed_input)
        moving_image = _load_ants_image(moving_input)
        fixed_mask_image = _load_ants_image(fixed_mask) if fixed_mask is not None else None
        moving_mask_image = _load_ants_image(moving_mask) if moving_mask is not None else None
        start = time.time()
        with _itk_thread_env(threads):
            tx = ants.registration(
                fixed=fixed_image,
                moving=moving_image,
                fixed_mask=fixed_mask_image,
                moving_mask=moving_mask_image,
                verbose=verbose,
                type_of_transform=f"antsRegistrationSyN[{transform}]",
            )
        return tx, round(time.time() - start, 1)

    def transform(self, fixed_image, moving_image, transform, interpolator_mode: str = "linear", threads: int | None = None):
        ants = _import_ants()
        fixed = _load_ants_image(fixed_image)
        moving = _load_ants_image(moving_image)
        with _itk_thread_env(threads):
            return ants.apply_transforms(
                fixed=fixed,
                moving=moving,
                transformlist=[str(path) for path in transform],
                interpolator=interpolator_mode,
            )

    def save_all_transforms(self, ants_transform_list: dict, dir_prefix_path: str | Path) -> dict[str, list[Path]]:
        return save_all_transforms(ants_transform_list, dir_prefix_path)


def require_cli(command: str) -> str:
    path = shutil.which(command)
    if not path:
        raise ANTsError(f"Required ANTs command not found on PATH: {command}")
    return path


def run_cli(cmd: list[str], verbose: bool = False, threads: int | None = None) -> None:
    env = None
    if threads is not None:
        env = os.environ.copy()
        env["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = str(max(1, int(threads)))
    run_checked(cmd, verbose=verbose, env=env, error_cls=ANTsError, error_prefix=cmd[0])


def register_cli(
    fixed,
    moving,
    out_prefix: str | Path,
    transform: str = "sr",
    fixed_mask=None,
    verbose: bool = False,
    threads: int | None = None,
) -> dict[str, list[Path]]:
    require_cli("antsRegistrationSyN.sh")
    fixed_path = _as_image_path(fixed)
    moving_path = _as_image_path(moving)
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mrsiprep_antscli_") as tmpdir:
        cli_prefix = Path(tmpdir) / "ants_"
        cmd = [
            "antsRegistrationSyN.sh",
            "-d",
            "3",
            "-f",
            str(fixed_path),
            "-m",
            str(moving_path),
            "-o",
            str(cli_prefix),
            "-t",
            transform,
        ]
        if fixed_mask is not None:
            cmd.extend(["-x", str(_as_image_path(fixed_mask))])
        run_cli(cmd, verbose=verbose, threads=threads)
        affine = cli_prefix.with_name(cli_prefix.name + "0GenericAffine.mat")
        warp = cli_prefix.with_name(cli_prefix.name + "1Warp.nii.gz")
        inverse_warp = cli_prefix.with_name(cli_prefix.name + "1InverseWarp.nii.gz")
        outputs = {
            "forward": [out_prefix.with_suffix(".syn.nii.gz"), out_prefix.with_suffix(".affine.mat")],
            "inverse": [out_prefix.with_suffix(".affine_inv.mat"), out_prefix.with_suffix(".syn_inv.nii.gz")],
        }
        _copy_required(warp, outputs["forward"][0])
        _copy_required(affine, outputs["forward"][1])
        _copy_required(affine, outputs["inverse"][0])
        _copy_required(inverse_warp, outputs["inverse"][1])
    return outputs


def apply_transforms_cli(
    fixed,
    moving,
    transforms: list[str | Path],
    out_path: str | Path,
    interpolation: str = "linear",
    threads: int | None = None,
) -> Path:
    require_cli("antsApplyTransforms")
    existing = [Path(path) for path in transforms if Path(path).exists()]
    if not existing:
        raise ANTsError(f"No transform files exist in list: {transforms}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "antsApplyTransforms",
        "-d",
        "3",
        "-i",
        str(_as_image_path(moving)),
        "-r",
        str(_as_image_path(fixed)),
        "-o",
        str(out_path),
        "-n",
        _cli_interpolation(interpolation),
    ]
    for transform in existing:
        if transform.name.endswith(".affine_inv.mat"):
            cmd.extend(["-t", f"[{transform},1]"])
        else:
            cmd.extend(["-t", str(transform)])
    run_cli(cmd, threads=threads)
    return out_path


def _as_image_path(image) -> Path:
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.exists():
            raise ANTsError(f"Image path does not exist: {path}")
        return path
    if isinstance(image, nib.Nifti1Image):
        tmp = tempfile.NamedTemporaryFile(suffix=".nii.gz", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        nib.save(image, str(tmp_path))
        return tmp_path
    raise ANTsError("ANTs CLI fallback requires image paths or nibabel images.")


def _copy_required(source: Path, target: Path) -> None:
    if not source.exists():
        raise ANTsError(f"ANTs CLI did not create expected transform: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _cli_interpolation(interpolation: str) -> str:
    mapping = {
        "linear": "Linear",
        "nearestNeighbor": "NearestNeighbor",
        "genericLabel": "GenericLabel",
        "bSpline": "BSpline",
    }
    return mapping.get(interpolation, interpolation)

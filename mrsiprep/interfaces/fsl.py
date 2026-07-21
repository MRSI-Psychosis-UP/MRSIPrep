"""FSL FLIRT registration interface (FNIRT is not implemented)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import nibabel as nib

from mrsiprep.utils.subprocess_utils import run_checked


class FSLError(RuntimeError):
    """Raised when FSL cannot complete a requested operation."""


def require_cli(command: str) -> str:
    path = shutil.which(command)
    if not path:
        raise FSLError(f"Required FSL command not found on PATH: {command}")
    return path


def require(command: str) -> str:
    return require_cli(command)


def run_cli(cmd: list[str], verbose: bool = False) -> None:
    run_checked(cmd, verbose=verbose, error_cls=FSLError, error_prefix=cmd[0])


def run_fast(t1_path: str | Path, out_prefix: str | Path, verbose: bool = False) -> dict[str, Path]:
    require_cli("fast")
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["fast", "-t", "1", "-n", "3", "-H", "0.1", "-I", "4", "-l", "20.0", "-o", str(out_prefix), str(t1_path)]
    run_checked(cmd, verbose=verbose, error_cls=FSLError, error_prefix="fast")
    return {
        "CSF": out_prefix.parent / f"{out_prefix.name}_pve_0.nii.gz",
        "GM": out_prefix.parent / f"{out_prefix.name}_pve_1.nii.gz",
        "WM": out_prefix.parent / f"{out_prefix.name}_pve_2.nii.gz",
    }


def register_flirt(
    fixed,
    moving,
    out_prefix: str | Path,
    *,
    fixed_mask=None,
    flirt_dof: int = 12,
    flirt_cost: str = "mutualinfo",
    flirt_init: str = "flirt",
    verbose: bool = False,
) -> dict[str, list[Path]]:
    """Register ``moving`` to ``fixed`` with FLIRT (affine only; no FNIRT).

    FLIRT-only is the entire ``fsl`` registration backend for now -- there is
    no deformable stage, unlike ANTs' default ``sr``/``s`` presets which add a
    SyN warp. This is a documented fidelity gap, not an oversight: FNIRT
    integration was scoped out.
    """
    require_cli("flirt")
    require_cli("convert_xfm")
    fixed_path = _as_image_path(fixed)
    moving_path = _as_image_path(moving)
    fixed_mask_path = _as_image_path(fixed_mask) if fixed_mask is not None else None
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    affine = out_prefix.with_suffix(".flirt.mat")
    inverse_affine = out_prefix.with_suffix(".flirt_inv.mat")

    with tempfile.TemporaryDirectory(prefix="mrsiprep_fslreg_") as tmpdir:
        tmp_registered = Path(tmpdir) / "flirt_registered.nii.gz"
        if flirt_init == "usesqform":
            cmd = [
                "flirt",
                "-in",
                str(moving_path),
                "-ref",
                str(fixed_path),
                "-applyxfm",
                "-usesqform",
                "-omat",
                str(affine),
                "-out",
                str(tmp_registered),
            ]
        elif flirt_init == "flirt":
            cmd = [
                "flirt",
                "-in",
                str(moving_path),
                "-ref",
                str(fixed_path),
                "-omat",
                str(affine),
                "-out",
                str(tmp_registered),
                "-dof",
                str(flirt_dof),
                "-cost",
                flirt_cost,
            ]
            if fixed_mask_path is not None:
                cmd.extend(["-refweight", str(fixed_mask_path)])
        else:
            raise FSLError(f"Unsupported FLIRT initialization mode: {flirt_init}")
        run_cli(cmd, verbose=verbose)

    _invert_affine(affine, inverse_affine, verbose=verbose)
    return {"forward": [affine], "inverse": [inverse_affine]}


def apply_transforms(
    fixed,
    moving,
    transforms: list[str | Path],
    out_path: str | Path,
    interpolation: str = "linear",
    verbose: bool = False,
) -> Path:
    """Apply FLIRT affine transform(s). Multiple affines (e.g. mrsi->t1w
    composed with t1w->mni) are concatenated into a single matrix with
    ``convert_xfm -concat`` before being applied in one ``flirt -applyxfm``
    call -- FLIRT has no native multi-transform chaining like ANTs'
    ``apply_transforms -t A -t B``.

    ``transforms`` is expected in the same order ANTs uses: last-applied-first
    to the moving image (i.e. transforms[-1] is applied to ``moving`` first,
    transforms[0] last, matching ``mrsiprep.mrsi.resampling.transform_mrsi_maps``'
    ``list(t1_to_mni) + list(mrsi_to_t1)`` construction).
    """
    existing = [Path(path) for path in transforms if Path(path).exists()]
    if not existing:
        raise FSLError(f"No transform files exist in list: {transforms}")
    fixed_path = _as_image_path(fixed)
    moving_path = _as_image_path(moving)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if len(existing) == 1:
        _apply_affine(fixed_path, moving_path, existing[0], out_path, interpolation=interpolation, verbose=verbose)
        return out_path
    with tempfile.TemporaryDirectory(prefix="mrsiprep_fslconcat_") as tmpdir:
        combined = Path(tmpdir) / "combined.mat"
        # Applied to moving first -> last in ANTs-order convention.
        applied_first, *rest = reversed(existing)
        current = applied_first
        for next_transform in rest:
            require_cli("convert_xfm")
            run_cli(["convert_xfm", "-omat", str(combined), "-concat", str(next_transform), str(current)], verbose=verbose)
            current = combined
        _apply_affine(fixed_path, moving_path, combined, out_path, interpolation=interpolation, verbose=verbose)
    return out_path


def _invert_affine(affine: Path, inverse_affine: Path, verbose: bool = False) -> None:
    require_cli("convert_xfm")
    run_cli(["convert_xfm", "-omat", str(inverse_affine), "-inverse", str(affine)], verbose=verbose)


def _apply_affine(fixed: Path, moving: Path, affine: Path, out_path: Path, interpolation: str, verbose: bool = False) -> None:
    require_cli("flirt")
    cmd = [
        "flirt",
        "-in",
        str(moving),
        "-ref",
        str(fixed),
        "-applyxfm",
        "-init",
        str(affine),
        "-out",
        str(out_path),
        "-interp",
        _flirt_interpolation(interpolation),
    ]
    run_cli(cmd, verbose=verbose)


def _as_image_path(image) -> Path:
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.exists():
            raise FSLError(f"Image path does not exist: {path}")
        return path
    if isinstance(image, nib.Nifti1Image):
        tmp = tempfile.NamedTemporaryFile(suffix=".nii.gz", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        nib.save(image, str(tmp_path))
        return tmp_path
    raise FSLError("FSL interface requires image paths or nibabel images.")


def _flirt_interpolation(interpolation: str) -> str:
    mapping = {
        "linear": "trilinear",
        "nearestNeighbor": "nearestneighbour",
        "genericLabel": "nearestneighbour",
        "bSpline": "spline",
    }
    return mapping.get(interpolation, interpolation)

"""Image helpers."""

from __future__ import annotations

import re
from pathlib import Path

import nibabel as nib
import numpy as np


def load_data(path: str | Path, dtype=np.float32) -> tuple[nib.Nifti1Image, np.ndarray]:
    img = nib.load(str(path))
    return img, np.asanyarray(img.dataobj).astype(dtype)


def nifti_validity_error(path: str | Path) -> str | None:
    """Force-read a NIfTI's header and voxel data; return an error message if
    it's missing, unreadable, or truncated/corrupted, else None.

    ``nib.load`` only parses the header lazily -- it does not by itself
    detect a truncated gzip stream or corrupted data block, so this also
    forces a full read via ``.dataobj`` (mirroring the read every mrsiprep
    step performs downstream, just done here upfront during preflight).
    """
    path = Path(path)
    if not path.exists():
        return f"File not found: {path}"
    try:
        img = nib.load(str(path))
        np.asanyarray(img.dataobj)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any read failure means "unusable input"
        return f"{type(exc).__name__}: {exc}"
    return None


def load_3d_data(path: str | Path, dtype=np.float32, label: str = "image") -> tuple[nib.Nifti1Image, np.ndarray]:
    img, data = load_data(path, dtype=dtype)
    data = np.squeeze(data)
    if data.ndim != 3:
        raise ValueError(f"Expected 3D {label}, got shape {data.shape}: {path}")
    return img, data


def save_nifti(data: np.ndarray, reference: nib.Nifti1Image | str | Path, out_path: str | Path, dtype=None) -> Path:
    if isinstance(reference, nib.Nifti1Image):
        ref_img = reference
    else:
        ref_img = nib.load(str(reference))
    header = ref_img.header.copy()
    if dtype is not None:
        header.set_data_dtype(dtype)
        data = data.astype(dtype)
    else:
        header.set_data_dtype(data.dtype)
    header.set_data_shape(data.shape)
    out_img = nib.Nifti1Image(data, ref_img.affine, header)
    out_img.set_qform(ref_img.affine, code=int(ref_img.header["qform_code"]) if "qform_code" in ref_img.header else 1)
    out_img.set_sform(ref_img.affine, code=int(ref_img.header["sform_code"]) if "sform_code" in ref_img.header else 1)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(out_img, str(out_path))
    return out_path


def valid_nifti(path: str | Path | None, allow_zeros: bool = False) -> bool:
    if path is None:
        return False
    path = Path(path)
    if not path.exists():
        return False
    try:
        data = np.asanyarray(nib.load(str(path)).dataobj)
    except Exception:
        return False
    if data.size == 0:
        return False
    if np.issubdtype(data.dtype, np.floating) and not np.isfinite(data).all():
        return False
    return allow_zeros or bool(np.nanmax(data) != 0)


def assert_same_grid(paths: list[Path], label: str = "images") -> None:
    if not paths:
        return
    first = nib.load(str(paths[0]))
    for path in paths[1:]:
        img = nib.load(str(path))
        if img.shape[:3] != first.shape[:3]:
            raise ValueError(f"{label} do not share shape: {paths[0]} {first.shape} vs {path} {img.shape}")
        if not np.allclose(img.affine, first.affine, atol=1e-3):
            raise ValueError(f"{label} do not share affine: {paths[0]} vs {path}")


def mean_resolution(path: str | Path) -> float:
    img = nib.load(str(path))
    return float(np.mean(img.header.get_zooms()[:3]))


def round_mm_resolution(value: float) -> int:
    return max(1, round(value))


def resolve_mni_resolution(choice: str, t1_path: str | Path, mrsi_path: str | Path | None = None) -> int:
    """Resolve ``--mni-resolution`` (origres/t1wres/<N>mm) to an integer mm resolution."""
    choice = str(choice).strip().lower()
    if choice == "t1wres":
        return round_mm_resolution(mean_resolution(t1_path))
    if choice == "origres":
        if mrsi_path is None:
            raise ValueError("origres MNI resolution requested but no MRSI reference path was provided.")
        return round_mm_resolution(mean_resolution(mrsi_path))
    match = re.search(r"(\d+)mm", choice)
    if match:
        return int(match.group(1))
    raise ValueError(f"Unsupported --mni-resolution value: {choice!r}. Use 'origres', 't1wres', or '<N>mm'.")

"""Partial-volume correction via PETPVC."""

from __future__ import annotations

import shutil
from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.utils.images import load_3d_data, save_nifti
from mrsiprep.utils.subprocess_utils import run_checked


class PVCError(RuntimeError):
    """Raised when partial-volume correction fails."""


def create_tissue_4d(config, subject: str, session: str | None, tissue_mrsi: dict[str, Path], reference: Path) -> Path:
    """Stack the GM/WM/CSF tissue-fraction maps into the single 4D volume
    petpvc's -m argument requires. Fully reconstructable from those three
    files, so it's a --work-dir scratch file rather than a derivative."""
    out = config.work_dir / f"sub-{subject}" / (f"ses-{session}" if session else "ses-none") / "pvc" / f"sub-{subject}_desc-4Dtissue_mrsi.nii.gz"
    if out.exists() and not (config.overwrite_pve or config.overwrite):
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    ref_img = nib.load(str(reference))
    data = np.stack([load_3d_data(tissue_mrsi[label], dtype=np.float32, label=f"{label} tissue map")[1] for label in ("GM", "WM", "CSF")], axis=-1)
    return save_nifti(data.astype(np.float32), ref_img, out, dtype=np.float32)


def run_pvc(config, subject: str, session: str | None, metabolite_maps: dict[str, Path], tissue_4d: Path, brainmask: Path, psf_width: float = 5.0) -> dict[str, Path]:
    if shutil.which("petpvc") is None:
        raise PVCError("petpvc command not found on PATH. Use --no-pvc to skip partial-volume correction.")
    _, brain_data = load_3d_data(brainmask, dtype=np.float32, label="MRSI brain mask")
    brain = brain_data.astype(bool)
    out_maps: dict[str, Path] = {}
    for met, path in metabolite_maps.items():
        out = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", met=met, desc="pvc", suffix_override="mrsi")
        if out.exists() and not (config.overwrite_pve or config.overwrite):
            out_maps[met] = out
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = out.with_name(out.name.replace("_desc-pvc_", "_desc-petpvcraw_"))
        cmd = ["petpvc", "-i", str(path), "-m", str(tissue_4d), "-p", "RBV", "-x", str(psf_width), "-y", str(psf_width), "-z", str(psf_width), "-o", str(tmp_out)]
        result = run_checked(cmd, check=False)
        if result.returncode != 0:
            details = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
            message = f"PETPVC RBV failed for {met} with exit status {result.returncode}"
            if details:
                message = f"{message}:\n{details}"
            raise PVCError(message)
        img = nib.load(str(tmp_out))
        _, raw = load_3d_data(path, dtype=np.float32, label=f"{met} map")
        data = np.squeeze(img.get_fdata(dtype=np.float32))
        if data.ndim != 3:
            raise PVCError(f"Expected 3D PETPVC output for {met}, got shape {data.shape}: {tmp_out}")
        data[data > 2 * raw] = 0
        data[data < 0] = 0
        data[~brain] = 0
        out_maps[met] = save_nifti(data.astype(np.float32), img, out, dtype=np.float32)
    return out_maps

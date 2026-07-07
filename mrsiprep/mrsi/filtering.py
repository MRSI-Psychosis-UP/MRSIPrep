"""Biharmonic-style MRSI spike filtering.

Ports the exact two-stage repair algorithm from mrsitoolbox's
``mrsitoolbox.filters.biharmonic.BiHarmonic.proc`` (median-filter spike
repair, then biharmonic inpainting of missing voxels, then masked
smoothing) so mrsiprep's spike-filtered output matches the legacy
pipeline without depending on mrsitoolbox at runtime.
"""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
from nilearn import image as nil_image
from scipy.ndimage import generic_filter
from skimage.restoration import inpaint_biharmonic

from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.utils.images import load_3d_data, save_nifti


def filter_metabolite_maps(config, subject: str, session: str | None, metabolite_maps: dict[str, Path], brainmask: Path) -> dict[str, Path]:
    if not config.filter_biharmonic:
        return metabolite_maps
    _, brain_data = load_3d_data(brainmask, dtype=np.float32, label="MRSI brain mask")
    brain = brain_data.astype(bool)
    filtered: dict[str, Path] = {}
    for met, path in metabolite_maps.items():
        out = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", met=met, desc="preproc", suffix_override="mrsi")
        if out.exists() and not (config.overwrite_filt or config.overwrite):
            filtered[met] = out
            continue
        img, data = load_3d_data(path, dtype=np.float32, label=f"{met} map")
        data = np.nan_to_num(data, nan=0.0)
        spike_mask = get_spike_mask(data, percentile=config.spike_percentile)
        repaired, missing = biharmonic_repair(data, brain, spike_mask, img.header, img.affine)
        filtered[met] = save_nifti(repaired.astype(np.float32), img, out, dtype=np.float32)
        spike_out = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", met=met, desc="spikemask", suffix_override="mask")
        save_nifti(spike_mask.astype(np.uint8), img, spike_out, dtype=np.uint8)
    return filtered


def get_spike_mask(data: np.ndarray, percentile: float = 99.0) -> np.ndarray:
    inside = data > 0
    if not np.any(inside):
        return np.zeros_like(data, dtype=bool)
    threshold = np.percentile(data[inside], percentile)
    return data > threshold


def biharmonic_repair(data: np.ndarray, brain: np.ndarray, spike_mask: np.ndarray, header, affine: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two-stage spike repair matching ``BiHarmonic.proc``.

    1. Replace spikes with a local 3x3x3 median (excluding the center voxel).
    2. Biharmonic-inpaint voxels that are still zero inside the brain mask.
    3. Smooth with FWHM derived from the image's own voxel size, splicing the
       smoothed values back in only at repaired locations.
    """
    unspiked = _inpaint_voxels_with_median(data, spike_mask)
    missing = np.zeros_like(unspiked, dtype=bool)
    missing[(unspiked == 0) & brain] = True
    inpainted = unspiked.copy()
    if np.any(missing):
        defect = unspiked.copy()
        defect[missing] = 0
        inpainted = inpaint_biharmonic(defect, missing)
    voxel_dims = np.array(header.get_zooms()[:3])
    fwhm = float(np.round(voxel_dims.mean() * np.sqrt(2)))
    smoothed = nil_image.smooth_img(nib.Nifti1Image(inpainted.astype(np.float32), affine), fwhm=fwhm).get_fdata()
    inpaint_mask = spike_mask | missing
    repaired = inpainted.copy()
    repaired[inpaint_mask] = smoothed[inpaint_mask]
    repaired[~brain] = 0
    return repaired, missing


def _inpaint_voxels_with_median(image: np.ndarray, mask: np.ndarray, filter_size: int = 3) -> np.ndarray:
    if not np.any(mask):
        return image.copy()
    median_image = generic_filter(image, _median_exclude_center, size=filter_size, mode="mirror")
    filtered = image.copy()
    filtered[mask] = median_image[mask]
    return filtered


def _median_exclude_center(values: np.ndarray) -> float:
    center = len(values) // 2
    neighbors = np.concatenate((values[:center], values[center + 1 :]))
    return float(np.median(neighbors))

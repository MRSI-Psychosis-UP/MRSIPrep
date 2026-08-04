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
from scipy import ndimage
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
        out = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", met=met, desc="signalspikefilt", suffix_override="mrsi")
        if out.exists() and not (config.overwrite_filt or config.overwrite):
            filtered[met] = out
            continue
        img, data = load_3d_data(path, dtype=np.float32, label=f"{met} map")
        data = np.nan_to_num(data, nan=0.0)
        max_cluster = config.spike_max_cluster_voxels
        if max_cluster is None:
            max_cluster = default_spike_max_cluster_voxels(img.header.get_zooms()[:3])
        spike_mask = get_spike_mask(data, percentile=config.spike_percentile, max_cluster_voxels=max_cluster)
        repaired, missing = biharmonic_repair(data, brain, spike_mask, img.header, img.affine, fwhm_mm=config.filter_fwhm_mm)
        filtered[met] = save_nifti(repaired.astype(np.float32), img, out, dtype=np.float32)
        spike_out = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", met=met, desc="spikemask", suffix_override="mask")
        save_nifti(spike_mask.astype(np.uint8), img, spike_out, dtype=np.uint8)
    return filtered


def default_spike_max_cluster_voxels(voxel_mm: tuple[float, float, float]) -> int:
    """Default cap on a spike cluster's voxel count before it's treated as
    real focal signal rather than noise, auto-scaled to the MRSI
    acquisition's native voxel size.

    A connected cluster of spike-thresholded voxels that's large and
    spatially coherent is more likely a real, focal signal feature (e.g. an
    actual metabolic abnormality) than sensor/reconstruction noise, which
    tends to hit isolated single voxels. Filtering (median-repair +
    biharmonic inpaint) should only apply to the small, isolated case.

    Derived empirically from connected-component cluster-size distributions
    of ``get_spike_mask()`` (default ``percentile=99``) computed across
    real acquisitions: 1075 3T metabolite maps (BioPsych-Project +
    Mindfulness-Project, ~5.0mm isotropic) and 445 7T metabolite maps
    (22q11-Project, ~3.4mm isotropic). The chosen cutoff is each field
    strength's 90th-percentile cluster size (3T: 6 voxels, 7T: 9 voxels) --
    conservative enough to still repair the large majority (>=90%) of real
    noise clusters, while protecting genuinely large focal clusters from
    being smoothed away. Since voxel size is what's actually available at
    runtime (not a field-strength tag), this maps voxel volume to the
    nearer of the two measured field-strength regimes by proximity to their
    respective native voxel volumes (3T ~5.0mm, 7T ~3.4mm isotropic),
    rather than hardcoding a scanner-specific lookup.
    """
    volume_mm3 = float(np.prod(voxel_mm))
    volume_3t = 5.0**3
    volume_7t = 3.4**3
    return 6 if abs(volume_mm3 - volume_3t) <= abs(volume_mm3 - volume_7t) else 9


def get_spike_mask(data: np.ndarray, percentile: float = 99.0, max_cluster_voxels: int | None = None) -> np.ndarray:
    """Voxels exceeding ``percentile`` of positive signal, restricted to
    connected clusters no larger than ``max_cluster_voxels`` (26-connectivity).

    ``max_cluster_voxels=None`` disables cluster-size filtering, matching
    the original flat per-voxel threshold behavior (every above-threshold
    voxel is treated as a spike, regardless of how large its connected
    cluster is).
    """
    inside = data > 0
    if not np.any(inside):
        return np.zeros_like(data, dtype=bool)
    threshold = np.percentile(data[inside], percentile)
    spike_mask = data > threshold
    if max_cluster_voxels is None or not np.any(spike_mask):
        return spike_mask
    labeled, n_clusters = ndimage.label(spike_mask, structure=np.ones((3, 3, 3)))
    cluster_sizes = ndimage.sum(spike_mask, labeled, index=np.arange(1, n_clusters + 1))
    oversized_labels = np.flatnonzero(cluster_sizes > max_cluster_voxels) + 1
    if oversized_labels.size:
        spike_mask = spike_mask & ~np.isin(labeled, oversized_labels)
    return spike_mask


def biharmonic_repair(
    data: np.ndarray, brain: np.ndarray, spike_mask: np.ndarray, header, affine: np.ndarray, fwhm_mm: float | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Two-stage spike repair matching ``BiHarmonic.proc``.

    1. Replace spikes with a local 3x3x3 median (excluding the center voxel).
    2. Biharmonic-inpaint voxels that are still zero inside the brain mask.
    3. Smooth with FWHM ``fwhm_mm`` (or, when unset, the native MRSI voxel
       size), splicing the smoothed values back in only at repaired
       locations.
    """
    unspiked = _inpaint_voxels_with_median(data, spike_mask)
    missing = np.zeros_like(unspiked, dtype=bool)
    missing[(unspiked == 0) & brain] = True
    inpainted = unspiked.copy()
    if np.any(missing):
        defect = unspiked.copy()
        defect[missing] = 0
        inpainted = inpaint_biharmonic(defect, missing)
    if fwhm_mm is not None:
        fwhm = float(fwhm_mm)
    else:
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

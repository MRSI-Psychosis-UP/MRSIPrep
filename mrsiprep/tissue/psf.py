"""MIDAS-style PSF-based tissue-fraction convolution.

Replicates the tissue-contribution image formation of Maudsley et al. 2006
(Fig. 3): the high-resolution tissue segmentation is convolved with the MRSI
3D spatial response function (a k-space-truncated, apodized sinc) before being
resampled to the MRSI grid, so that partial-volume fractions reflect the true
(wide, sinc-like) MRSI voxel response rather than a plain linear-interpolation
resample of a near-delta-response probability map.

This is the MIDAS-mode-only path; the existing
``mrsiprep.tissue.fractions.resample_tissue_to_mrsi`` (plain linear resample)
is untouched and remains in use for mni-norm/parc-con modes.
"""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
from scipy.ndimage import convolve, convolve1d

from mrsiprep.registration.transforms import apply_image_transform
from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.utils.images import load_3d_data, save_nifti


def _sinc_axis(null_spacing_grid: float, alpha: float, truncation_radius: float) -> np.ndarray:
    """1-D Hamming-apodized sinc sampled on the (high-resolution) tissue grid.

    ``null_spacing_grid`` is the distance, in tissue-grid voxels, to the first
    sinc null -- i.e. the MRSI voxel size divided by the tissue-grid spacing
    (e.g. 5 mm / 1 mm = 5 grid voxels). The kernel therefore spans several grid
    voxels and genuinely blurs, rather than degenerating to a delta when
    sampled on the coarse MRSI grid (where the nulls would fall on every
    integer offset). A Hamming window over ``truncation_radius`` nulls tapers
    the side lobes to suppress Gibbs ringing, matching MIDAS's choice.
    """
    null_spacing = max(float(null_spacing_grid), 1e-6)
    half = max(1, int(round(truncation_radius * null_spacing)))
    offsets = np.arange(-half, half + 1, dtype=np.float64)
    sinc = np.sinc(offsets / null_spacing)
    window = alpha + (1.0 - alpha) * np.cos(np.pi * offsets / half)
    kernel = sinc * window
    total = kernel.sum()
    if total != 0:
        kernel = kernel / total
    return kernel


def hamming_sinc_psf_kernel(
    voxel_mm: tuple[float, float, float],
    grid_spacing_mm: tuple[float, float, float],
    alpha: float = 0.54,
    truncation_radius: float = 3.0,
) -> np.ndarray:
    """Separable 3D Hamming-apodized sinc kernel for the MRSI spatial response.

    ``voxel_mm`` is the MRSI voxel size (the width of the MRSI spatial response,
    i.e. the location of the first sinc null) and ``grid_spacing_mm`` the
    spacing of the grid the kernel is applied on -- the high-resolution T1w/
    tissue grid, so ``voxel_mm / grid_spacing_mm`` is the null spacing in grid
    voxels. ``truncation_radius`` sets the support in units of that null
    spacing. Returned kernel is normalized to sum 1.
    """
    axes = psf_axes(voxel_mm, grid_spacing_mm, alpha=alpha, truncation_radius=truncation_radius)
    kernel = np.einsum("i,j,k->ijk", axes[0], axes[1], axes[2])
    total = kernel.sum()
    if total != 0:
        kernel = kernel / total
    return kernel.astype(np.float64)


def psf_axes(
    voxel_mm: tuple[float, float, float],
    grid_spacing_mm: tuple[float, float, float],
    alpha: float = 0.54,
    truncation_radius: float = 3.0,
) -> list[np.ndarray]:
    """The three separable 1D Hamming-sinc axes of the MRSI PSF (per axis).

    The full 3D kernel is their outer product; keeping them separable lets
    ``convolve_with_psf_separable`` apply three cheap 1D convolutions instead of
    one dense O(K^3) 3D convolution.
    """
    return [
        _sinc_axis(size / max(spacing, 1e-6), alpha, truncation_radius)
        for size, spacing in zip(voxel_mm, grid_spacing_mm)
    ]


def convolve_with_psf_separable(data: np.ndarray, axes: list[np.ndarray]) -> np.ndarray:
    """Edge-normalized separable convolution: apply the three 1D PSF axes in
    sequence. Equivalent to ``convolve_with_psf`` with the outer-product kernel
    but far faster on large volumes (O(N*K) vs O(N*K^3))."""
    data = np.nan_to_num(np.asarray(data, dtype=np.float64), copy=False)
    numerator = data
    support = np.ones_like(data)
    for axis, weights in enumerate(axes):
        numerator = convolve1d(numerator, weights, axis=axis, mode="constant", cval=0.0)
        support = convolve1d(support, weights, axis=axis, mode="constant", cval=0.0)
    return np.divide(numerator, support, out=np.zeros_like(numerator), where=support > 1e-8)


def convolve_with_psf(data: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Convolve ``data`` with ``kernel``, normalized against edge falloff.

    Convolving against implicit zero padding attenuates voxels near the image
    boundary; dividing by the convolution of an all-ones support map restores
    them (same edge-handling idea as the biharmonic smoothing in
    ``mrsi/filtering.py``).
    """
    data = np.nan_to_num(np.asarray(data, dtype=np.float64), copy=False)
    numerator = convolve(data, kernel, mode="constant", cval=0.0)
    support = convolve(np.ones_like(data), kernel, mode="constant", cval=0.0)
    out = np.divide(numerator, support, out=np.zeros_like(numerator), where=support > 1e-8)
    return out


def resample_tissue_to_mrsi_psf(
    config,
    subject: str,
    session: str | None,
    tissue_t1: dict[str, Path],
    mrsi_reference: Path,
    t1_to_mrsi_transforms: list[Path],
    alpha: float = 0.54,
    truncation_radius: float = 3.0,
) -> dict[str, Path]:
    """MIDAS-mode sibling of ``resample_tissue_to_mrsi`` (MIDAS Fig. 3).

    Convolves each high-resolution T1w-space tissue map with the MRSI spatial
    response function (a Hamming-apodized sinc whose first null sits at the MRSI
    voxel width) *before* resampling to the MRSI grid, so partial-volume
    fractions reflect the wide MRSI voxel response. Convolving in the T1w grid
    (where the ~5 mm MRSI PSF spans several 1 mm voxels) is essential: doing it
    after downsampling to the coarse MRSI grid would sample the sinc on its own
    nulls and degenerate to a no-op. Outputs carry a ``desc-psf`` entity so they
    don't collide with, or reuse a stale cache from, the plain linear-resample
    fractions.
    """
    mrsi_img = nib.load(str(mrsi_reference))
    mrsi_voxel_mm = tuple(float(z) for z in mrsi_img.header.get_zooms()[:3])

    out: dict[str, Path] = {}
    for label, path in tissue_t1.items():
        target = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", label=label, desc="psf", suffix_override="probseg")
        if target.exists() and not (config.overwrite_seg or config.overwrite):
            out[label] = target
            continue
        # Convolve with the MRSI PSF in the high-res T1w grid, then resample.
        # Use the separable 1D form -- orders of magnitude faster than a dense
        # 3D convolution with the (often 30+ voxel wide) kernel.
        t1_img, t1_data = load_3d_data(path, dtype="float32", label=f"{label} tissue map")
        t1_spacing_mm = tuple(float(z) for z in t1_img.header.get_zooms()[:3])
        axes = psf_axes(mrsi_voxel_mm, t1_spacing_mm, alpha=alpha, truncation_radius=truncation_radius)
        blurred = convolve_with_psf_separable(t1_data, axes)
        blurred = np.clip(blurred, 0.0, None)
        blurred_path = _blurred_scratch_path(config, subject, session, label)
        save_nifti(blurred.astype("float32"), t1_img, blurred_path, dtype="float32")
        out[label] = apply_image_transform(mrsi_reference, blurred_path, t1_to_mrsi_transforms, target, interpolation="linear", threads=config.nthreads)
    return out


def _blurred_scratch_path(config, subject: str, session: str | None, label: str) -> Path:
    scratch = config.work_dir / f"sub-{subject}" / (f"ses-{session}" if session else "ses-none") / "psf"
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch / f"sub-{subject}_label-{label}_desc-psfblurredT1w_probseg.nii.gz"

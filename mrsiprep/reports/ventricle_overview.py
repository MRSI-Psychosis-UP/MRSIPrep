"""Native-space ventricle visibility QC (MRSI Raw QC tab, after the
per-metabolite slice montages).

Purely a visual check, run in each recording's own native MRSI grid,
before any T1w coregistration touches the data: a cheap, prior-only
placement (translation + per-axis scale from brainmask centroid/extent,
no iterative registration) drops the Harvard-Oxford lateral-ventricle
prior into native space, then a local darker-than-surroundings threshold
detects what (if anything) actually looks like ventricle in each
metabolite's own raw signal. The slice with the most detected voxels is
rendered with the detected outline for visual inspection -- deliberately
not reduced to a pass/fail metric, since a naive summary ratio here has
already been shown to invert direction on real data (see
experiments/native_space_ventricle_qc.py); the outline itself, on its
best slice, is the informative artifact.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from mrsiprep.io.naming import coverage_report_dir, qc_report_derivative

_LEFT_LATERAL_VENTRICLE_IDX = 2
_RIGHT_LATERAL_VENTRICLE_IDX = 13
_HO_ATLAS_RELATIVE = Path("data/atlases/HarvardOxford/HarvardOxford-sub-prob-2mm.nii.gz")
_MNI_BRAIN_MASK_RELATIVE = Path("data/standard/MNI152_T1_2mm_brain_mask.nii.gz")


def _fsl_standard_path(relative: Path) -> Path | None:
    fsl_dir = os.environ.get("FSLDIR")
    if not fsl_dir:
        return None
    candidate = Path(fsl_dir) / relative
    return candidate if candidate.exists() else None


def _load_canonical(path: Path) -> tuple[np.ndarray, np.ndarray]:
    import nibabel as nib

    img = nib.as_closest_canonical(nib.load(str(path)))
    data = np.asarray(img.get_fdata())
    if data.ndim == 4:
        data = data[..., 0]
    return data, img.affine


def _lateral_ventricle_prior() -> tuple[np.ndarray, np.ndarray] | None:
    """Combined left+right lateral-ventricle probability (0-100), from
    FSL's Harvard-Oxford subcortical atlas. Returns None if FSLDIR or the
    atlas data isn't available, so callers can skip this QC section
    gracefully rather than fail the whole report over an optional check.
    """
    atlas_path = _fsl_standard_path(_HO_ATLAS_RELATIVE)
    if atlas_path is None:
        return None
    import nibabel as nib

    img = nib.as_closest_canonical(nib.load(str(atlas_path)))
    data = np.asarray(img.get_fdata())
    combined = np.clip(data[..., _LEFT_LATERAL_VENTRICLE_IDX] + data[..., _RIGHT_LATERAL_VENTRICLE_IDX], 0, 100)
    return combined, img.affine


def _mni_brain_mask() -> tuple[np.ndarray, np.ndarray] | None:
    mask_path = _fsl_standard_path(_MNI_BRAIN_MASK_RELATIVE)
    if mask_path is None:
        return None
    data, affine = _load_canonical(mask_path)
    return data > 0, affine


def _world_bbox_center_and_extent(mask: np.ndarray, affine: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import nibabel as nib

    idx = np.argwhere(mask)
    world = nib.affines.apply_affine(affine, idx)
    return world.mean(axis=0), world.max(axis=0) - world.min(axis=0)


def _mni_to_native_affine(
    native_mask: np.ndarray, native_affine: np.ndarray, mni_mask: np.ndarray, mni_affine: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Cheap translation + per-axis-scale placement from brainmask
    centroid/extent, no optimization. Per-axis (not isotropic) scaling
    matters because whole-brain MRSI's z-FOV is often heavily truncated
    relative to a full MNI head, so a single averaged scale factor
    mismatches z badly and can place the prior outside the true ventricle
    location entirely.
    """
    if not native_mask.any() or not mni_mask.any():
        return None
    mni_center, mni_extent = _world_bbox_center_and_extent(mni_mask, mni_affine)
    native_center, native_extent = _world_bbox_center_and_extent(native_mask, native_affine)
    if np.any(mni_extent <= 0):
        return None
    scale = native_extent / mni_extent
    return mni_center, native_center, scale


def _warp_prior_to_native(
    mni_prob: np.ndarray,
    mni_affine: np.ndarray,
    native_shape: tuple[int, int, int],
    native_affine: np.ndarray,
    mni_center: np.ndarray,
    native_center: np.ndarray,
    scale: np.ndarray,
    threshold: float = 50.0,
) -> np.ndarray:
    import nibabel as nib
    from scipy.ndimage import map_coordinates

    native_idx = np.array(np.meshgrid(*(np.arange(dim) for dim in native_shape), indexing="ij")).reshape(3, -1).T
    native_world = nib.affines.apply_affine(native_affine, native_idx)
    mni_world = mni_center + (native_world - native_center) / scale
    mni_vox = nib.affines.apply_affine(np.linalg.inv(mni_affine), mni_world)
    sampled = map_coordinates(mni_prob, mni_vox.T, order=1, mode="constant", cval=0.0)
    return (sampled >= threshold).reshape(native_shape)


def _detect_ventricle_mask(
    signal: np.ndarray, prior_roi: np.ndarray, brainmask: np.ndarray, search_dilate: int = 2, threshold_percentile: float = 35.0
) -> np.ndarray:
    """Data-driven detection within a dilation of the warped prior: keep
    voxels darker than a percentile of the local reference shell, so the
    result adapts to each recording's own signal/noise floor instead of
    trusting the prior placement alone. If nothing nearby is actually
    darker than its surroundings, this comes back empty/small -- itself
    informative, not a failure.
    """
    from scipy.ndimage import binary_dilation

    search_region = binary_dilation(prior_roi, iterations=search_dilate) & brainmask
    reference_shell = binary_dilation(search_region, iterations=1) & ~search_region & brainmask
    if reference_shell.sum() == 0:
        return np.zeros_like(prior_roi)
    threshold = np.percentile(signal[reference_shell], threshold_percentile)
    return search_region & (signal <= threshold)


def _best_slice_by_voxel_count(detected: np.ndarray, min_voxels: int = 3) -> int | None:
    counts = detected.sum(axis=(0, 1))
    if counts.max() < min_voxels:
        return None
    return int(np.argmax(counts))


def _render_ventricle_slice(signal: np.ndarray, prior_roi: np.ndarray, detected: np.ndarray, z: int, out_path: Path, met: str) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path.parent.mkdir(parents=True, exist_ok=True)
    finite = signal[np.isfinite(signal) & (signal > 0)]
    vmax = float(np.percentile(finite, 99)) if finite.size else float(np.nanmax(signal))

    fig, ax = plt.subplots(figsize=(3.2, 3.2), constrained_layout=True)
    ax.imshow(np.rot90(signal[:, :, z]), cmap="viridis", vmin=0, vmax=max(vmax, 1e-6))
    ax.contour(np.rot90(prior_roi[:, :, z]), levels=[0.5], colors="white", linewidths=1.0, linestyles="dashed")
    ax.contour(np.rot90(detected[:, :, z]), levels=[0.5], colors="red", linewidths=1.6)
    ax.set_title(f"{met}  (z={z})", fontsize=9)
    ax.axis("off")
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def build_ventricle_qc_sections(config, subject: str, session: str | None, raw_maps: dict[str, Path]) -> list[tuple[str, str]]:
    """One rendered slice per metabolite: wherever that metabolite's own
    raw signal shows the most plausible ventricle darkening, near the
    anatomically expected location. Native MRSI space only, run before any
    coregistration -- an acquisition-quality check, not a registration
    check. Returns [] (no section, not an error) if FSL's standard-space
    data isn't available, since this is a supplementary check on top of
    the required per-metabolite montages above it, not a hard dependency.
    """
    prior = _lateral_ventricle_prior()
    mni_brain = _mni_brain_mask()
    if prior is None or mni_brain is None:
        return []
    mni_vent_prob, mni_vent_affine = prior
    mni_brain_mask, mni_brain_affine = mni_brain

    out = qc_report_derivative(config.derivative_dir, subject, session, "mrsi-raw")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"

    images: list[str] = []
    for met in sorted(raw_maps):
        signal, affine = _load_canonical(raw_maps[met])
        brainmask = np.isfinite(signal) & (signal > 0)
        placement = _mni_to_native_affine(brainmask, affine, mni_brain_mask, mni_brain_affine)
        if placement is None:
            continue
        mni_center, native_center, scale = placement
        prior_roi = _warp_prior_to_native(mni_vent_prob, mni_vent_affine, signal.shape, affine, mni_center, native_center, scale)
        prior_roi &= brainmask
        detected = _detect_ventricle_mask(signal, prior_roi, brainmask)
        best_z = _best_slice_by_voxel_count(detected)
        if best_z is None:
            continue
        png_path = figures_dir / f"{out.stem}_met-{met}_ventricle-qc.png"
        _render_ventricle_slice(signal, prior_roi, detected, best_z, png_path, met)
        images.append(f"<div><img src='figures/{png_path.name}'></div>")

    if not images:
        return []
    body = (
        "<p>Native-MRSI-space ventricle visibility, before any T1w coregistration: a cheap MNI-prior "
        "placement (dashed white) and the resulting data-driven detection (red) on each metabolite's own "
        "best-contrast slice. A clean, anatomically plausible outline indicates well-resolved ventricles; "
        "a ragged, offset, or absent one is worth a closer look before trusting downstream registration.</p>"
        "<div class='row'>" + "".join(images) + "</div>"
    )
    return [("Ventricle visibility (pre-coregistration)", body)]

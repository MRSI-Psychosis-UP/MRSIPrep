"""Native-space prior-based QC (MRSI Raw QC tab, after the per-metabolite
slice montages): ventricle visibility, and an initial GM/WM contrast check
on the same slice.

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
    """Brain mask of the run's reference template.

    Taken from the same template the pipeline normalizes into
    (:mod:`mrsiprep.config.templates`) rather than from FSL's ``$FSLDIR``
    standard directory: FSL ships the MNI152NLin6Asym lineage, so the old
    source described a different space than the data being checked. Falls back
    to FSL's copy only if TemplateFlow cannot provide one, so the QC section
    degrades rather than disappearing.
    """
    import nibabel as nib

    from mrsiprep.config.templates import TemplateError, template_brain_mask

    try:
        img = nib.as_closest_canonical(template_brain_mask())
        return np.asarray(img.get_fdata()) > 0, img.affine
    except (TemplateError, OSError):
        mask_path = _fsl_standard_path(_MNI_BRAIN_MASK_RELATIVE)
        if mask_path is None:
            return None
        data, affine = _load_canonical(mask_path)
        return data > 0, affine


_FSL_GM_PRIOR_RELATIVE = Path("data/standard/tissuepriors/avg152T1_gray.hdr")
_FSL_WM_PRIOR_RELATIVE = Path("data/standard/tissuepriors/avg152T1_white.hdr")


def _tissue_priors() -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """GM and WM probability (0-1) in template space, plus their affine.

    Same source and same fallback policy as :func:`_mni_brain_mask`: the
    template the pipeline actually normalizes into, with FSL's copy used
    only if TemplateFlow cannot provide one. FSL's priors are 0-255 in a
    different template lineage (NLin6Asym), so they are rescaled here and
    are a degraded, not equivalent, substitute.

    Returns ``None`` when neither source is available, so the caller drops
    this QC row rather than failing the report.
    """
    import nibabel as nib

    from mrsiprep.config.templates import TemplateError, template_tissue_probseg

    try:
        gm_img = nib.as_closest_canonical(template_tissue_probseg("GM"))
        wm_img = nib.as_closest_canonical(template_tissue_probseg("WM"))
        return np.asarray(gm_img.get_fdata()), np.asarray(wm_img.get_fdata()), gm_img.affine
    except (TemplateError, OSError):
        gm_path = _fsl_standard_path(_FSL_GM_PRIOR_RELATIVE)
        wm_path = _fsl_standard_path(_FSL_WM_PRIOR_RELATIVE)
        if gm_path is None or wm_path is None:
            return None
        gm, affine = _load_canonical(gm_path)
        wm, _ = _load_canonical(wm_path)
        return gm / 255.0, wm / 255.0, affine


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


def _sample_prior_to_native(
    mni_prob: np.ndarray,
    mni_affine: np.ndarray,
    native_shape: tuple[int, int, int],
    native_affine: np.ndarray,
    mni_center: np.ndarray,
    native_center: np.ndarray,
    scale: np.ndarray,
) -> np.ndarray:
    """Resample an MNI probability map onto the native grid, unthresholded.

    The tissue QC needs to *compare* GM against WM probability per voxel, so
    it cannot use a pre-thresholded mask; the ventricle check thresholds this
    result itself.
    """
    import nibabel as nib
    from scipy.ndimage import map_coordinates

    native_idx = np.array(np.meshgrid(*(np.arange(dim) for dim in native_shape), indexing="ij")).reshape(3, -1).T
    native_world = nib.affines.apply_affine(native_affine, native_idx)
    mni_world = mni_center + (native_world - native_center) / scale
    mni_vox = nib.affines.apply_affine(np.linalg.inv(mni_affine), mni_world)
    sampled = map_coordinates(mni_prob, mni_vox.T, order=1, mode="constant", cval=0.0)
    return sampled.reshape(native_shape)


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
    sampled = _sample_prior_to_native(
        mni_prob, mni_affine, native_shape, native_affine, mni_center, native_center, scale
    )
    return sampled >= threshold


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


def _prior_slice_bias(prior_roi: np.ndarray) -> np.ndarray:
    """Gaussian weight over z, peaked where the warped prior actually puts
    the ventricles.

    Detection can pick up dark voxels far from the ventricles -- the
    inferior slices where the head leaves the excitation volume are the
    usual culprit, and they can carry more sub-threshold voxels than the
    ventricles themselves. Weighting by the prior's own centre of mass
    keeps the search near the expected location. Anchoring to the prior
    rather than to the middle of the array matters because the MRSI FOV is
    routinely asymmetric about the brain, so "the middle slice" and "where
    ventricles are" are not the same index.
    """
    counts = prior_roi.sum(axis=(0, 1)).astype(float)
    n_slices = prior_roi.shape[2]
    z = np.arange(n_slices, dtype=float)
    total = counts.sum()
    if total <= 0:
        center = (n_slices - 1) / 2.0
        sigma = max(n_slices / 6.0, 1.0)
    else:
        center = float((counts * z).sum() / total)
        spread = float(np.sqrt((counts * (z - center) ** 2).sum() / total))
        # Floor the width generously. The placement is a coarse bounding-box
        # affine, so it can sit a couple of slices off; a narrow prior would
        # otherwise turn this into a hard gate that pins the montage to a
        # mis-placed centre. At sigma=2 a slice 2 away is only mildly
        # penalised (x0.61) while one 5 away is strongly suppressed (x0.04),
        # which is the intended shape: break ties, never override the data.
        sigma = max(spread, 2.0)
    return np.exp(-0.5 * ((z - center) / sigma) ** 2)


def _estimate_wm_mask(
    signal: np.ndarray,
    gm_prob: np.ndarray,
    wm_prob: np.ndarray,
    brainmask: np.ndarray,
    core_prob: float = 0.7,
    min_core_voxels: int = 10,
) -> tuple[np.ndarray, float] | None:
    """Split the brain into WM and GM from the raw signal alone, using the
    warped prior only to seed which side is which.

    The prior supplies two confident cores (prior probability above
    ``core_prob``); their median signals set both the polarity and the
    threshold. Polarity has to be measured rather than assumed because it is
    metabolite-dependent -- NAA and Cho run higher in white matter, Ins
    higher in grey -- so a fixed "WM is brighter" rule would invert the
    outline for half the panel.

    Returns ``(wm_mask, contrast_percent)``, where the contrast is the
    difference between the two core medians as a percentage of their mean,
    or ``None`` when either core is too small for the placement to be
    trusted.

    Deliberately no smoothing: the whole point of the rendered outline is
    that its continuity attests to real GM/WM contrast, and filtering the
    signal first would manufacture exactly the continuity the reader is
    being asked to judge. A speckled outline is the honest answer for a
    metabolite with no usable tissue contrast.
    """
    wm_core = (wm_prob >= core_prob) & brainmask
    gm_core = (gm_prob >= core_prob) & brainmask
    if wm_core.sum() < min_core_voxels or gm_core.sum() < min_core_voxels:
        return None

    wm_median = float(np.median(signal[wm_core]))
    gm_median = float(np.median(signal[gm_core]))
    mean_level = (wm_median + gm_median) / 2.0
    if not np.isfinite(mean_level) or mean_level == 0:
        return None

    threshold = mean_level
    wm_mask = brainmask & ((signal >= threshold) if wm_median >= gm_median else (signal <= threshold))
    contrast = abs(wm_median - gm_median) / abs(mean_level) * 100.0
    return wm_mask, contrast


def _slice_counts(detected: np.ndarray) -> np.ndarray:
    """Raw detected-voxel count per axial slice."""
    return detected.sum(axis=(0, 1)).astype(float)


def _consensus_slice(counts: list[np.ndarray], biases: list[np.ndarray], min_voxels: int = 3) -> int | None:
    """One slice index for the whole montage, agreed across metabolites.

    Letting each metabolite pick its own argmax meant a single noisy map
    could land on an unrelated slice, so panels that should be directly
    comparable were not: the same recording rendered CrPCr at z=11 and
    GPCPCh at z=6.

    Each metabolite votes with its prior-biased profile normalised by its
    own peak, so a high-SNR metabolite cannot outvote the rest and the
    winner is the slice most metabolites agree on rather than the one with
    the largest absolute count.

    The ``min_voxels`` floor is applied to the *raw* counts, not the biased
    ones, so the bias only ever reorders candidate slices -- it can never
    manufacture a detection that isn't in the data. Returns ``None`` when no
    metabolite reaches ``min_voxels`` at the winning slice, preserving the
    previous "absent is itself informative" behaviour.
    """
    if not counts:
        return None
    votes = np.zeros(len(counts[0]), dtype=float)
    for count, bias in zip(counts, biases):
        weighted = count * bias
        peak = weighted.max()
        if peak > 0:
            votes += weighted / peak
    if votes.max() <= 0:
        return None
    best = int(np.argmax(votes))
    if max(float(count[best]) for count in counts) < min_voxels:
        return None
    return best


MAX_MONTAGE_COLUMNS = 5


def _render_ventricle_montage(
    panels: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]],
    z: int,
    out_path: Path,
    tissue: dict[str, tuple[np.ndarray, float]] | None = None,
) -> Path:
    """One combined figure, one subplot per metabolite, at most
    ``MAX_MONTAGE_COLUMNS`` per row -- e.g. 9 metabolites lays out as 5
    columns x 2 rows -- rather than a separate standalone image per
    metabolite.

    Every panel is drawn at the same slice ``z``, so the montage compares
    metabolites rather than compares slices; the index is stated once in the
    figure title instead of per panel.

    When ``tissue`` is given it adds a second band of rows below the
    ventricle rows, at the same slice, keyed by metabolite name and holding
    ``(wm_mask, contrast_percent)``. Metabolites missing
    from the dict get an empty panel, so columns stay aligned between the
    two bands.
    """
    import math

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = len(panels)
    n_cols = min(n, MAX_MONTAGE_COLUMNS)
    band_rows = math.ceil(n / MAX_MONTAGE_COLUMNS)
    n_rows = band_rows * (2 if tissue else 1)

    fig, axes = plt.subplots(n_rows, n_cols, figsize=(2.6 * n_cols, 2.7 * n_rows), constrained_layout=True, squeeze=False)

    def _background(ax, signal):
        finite = signal[np.isfinite(signal) & (signal > 0)]
        vmax = float(np.percentile(finite, 99)) if finite.size else float(np.nanmax(signal))
        ax.imshow(np.rot90(signal[:, :, z]), cmap="viridis", vmin=0, vmax=max(vmax, 1e-6))
        ax.axis("off")

    for index, (met, signal, prior_roi, detected) in enumerate(panels):
        row, col = index // n_cols, index % n_cols
        ax = axes[row][col]
        _background(ax, signal)
        ax.contour(np.rot90(prior_roi[:, :, z]), levels=[0.5], colors="white", linewidths=1.0, linestyles="dashed")
        ax.contour(np.rot90(detected[:, :, z]), levels=[0.5], colors="red", linewidths=1.6)
        ax.set_title(met, fontsize=9)
        if col == 0:
            ax.set_ylabel("ventricles", fontsize=8)
            ax.axis("on")
            ax.set_xticks([])
            ax.set_yticks([])

        if tissue is None:
            continue
        tissue_ax = axes[band_rows + row][col]
        _background(tissue_ax, signal)
        entry = tissue.get(met)
        if entry is None:
            tissue_ax.set_title("no tissue estimate", fontsize=8)
        else:
            # Data-driven boundary only. The prior outline is deliberately not
            # drawn here: it is a smooth, always-closed curve, and next to the
            # blue outline it reads as the answer the data should have given,
            # which is precisely the judgement the reader is meant to make
            # unaided from the blue outline's own continuity.
            wm_mask, contrast = entry
            tissue_ax.contour(np.rot90(wm_mask[:, :, z]), levels=[0.5], colors="deepskyblue", linewidths=1.6)
            tissue_ax.set_title(f"GM/WM  ({contrast:.0f}%)", fontsize=8)
        if col == 0:
            tissue_ax.set_ylabel("GM/WM", fontsize=8)
            tissue_ax.axis("on")
            tissue_ax.set_xticks([])
            tissue_ax.set_yticks([])

    fig.suptitle(f"consensus slice z={z}", fontsize=10)

    # Blank the trailing cells of each band separately: with two bands the
    # unused slots are not one contiguous run at the end of the grid.
    for index in range(n, band_rows * n_cols):
        row, col = index // n_cols, index % n_cols
        axes[row][col].axis("off")
        if tissue is not None:
            axes[band_rows + row][col].axis("off")

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

    tissue_priors = _tissue_priors()

    panels: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]] = []
    counts: list[np.ndarray] = []
    biases: list[np.ndarray] = []
    tissue: dict[str, tuple[np.ndarray, float]] = {}
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
        panels.append((met, signal, prior_roi, detected))
        counts.append(_slice_counts(detected))
        biases.append(_prior_slice_bias(prior_roi))

        if tissue_priors is None:
            continue
        gm_mni, wm_mni, tissue_affine = tissue_priors
        warp = (signal.shape, affine, mni_center, native_center, scale)
        gm_prob = _sample_prior_to_native(gm_mni, tissue_affine, *warp)
        wm_prob = _sample_prior_to_native(wm_mni, tissue_affine, *warp)
        estimate = _estimate_wm_mask(signal, gm_prob, wm_prob, brainmask)
        if estimate is not None:
            tissue[met] = estimate

    # Metabolites acquired on different grids cannot share a slice index;
    # this is not expected within one recording, but silently rendering
    # mismatched indices would be worse than skipping the check.
    if panels and len({panel[1].shape for panel in panels}) > 1:
        return []
    consensus_z = _consensus_slice(counts, biases)
    if not panels or consensus_z is None:
        return []
    png_path = figures_dir / f"{out.stem}_ventricle-qc.png"
    _render_ventricle_montage(panels, consensus_z, png_path, tissue or None)
    tissue_note = (
        "<br>The <b>GM/WM</b> row shows the same slice. A template GM/WM prior is placed by the same "
        "rigid-ish transform, its confident cores seed which side is which, and the boundary (blue) is then "
        "thresholded from each metabolite's own raw signal -- no smoothing, so the outline is not flattered. "
        "Read its <i>continuity</i>: a closed, anatomically shaped boundary attests to real GM/WM contrast in "
        "that metabolite; a speckled or absent one means there is little tissue contrast to exploit. Only the "
        "data-driven boundary is drawn, with no prior outline to compare against, so the judgement rests on "
        "the outline itself. The percentage is the GM-to-WM difference between the two prior cores. Polarity "
        "is measured per metabolite, since NAA and Cho run higher in white matter while Ins runs higher in grey."
        if tissue
        else ""
    )
    body = (
        "<p>Native-MRSI-space ventricle visibility, before any T1w coregistration: a cheap MNI-prior "
        "placement (dashed white) and the resulting data-driven detection (red). All metabolites are shown "
        f"at one consensus slice (z={consensus_z}), chosen by agreement across metabolites and biased toward "
        "where the prior places the ventricles, so the panels compare metabolites rather than slices. "
        "A clean, anatomically plausible outline indicates well-resolved ventricles; "
        "a ragged, offset, or absent one is worth a closer look before trusting downstream registration."
        f"{tissue_note}</p>"
        f"<img src='figures/{png_path.name}'>"
    )
    title = "Ventricle and GM/WM visibility (pre-coregistration)" if tissue else "Ventricle visibility (pre-coregistration)"
    return [(title, body)]

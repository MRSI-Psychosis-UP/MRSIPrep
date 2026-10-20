"""Ventricle visibility QC: is each metabolite map dark where the lateral
ventricles are?

CSF holds almost no metabolites, so in an intact map the lateral ventricles
show up as a dark region; motion blurs, displaces or erases them.

Detection runs in each recording's own native MRSI grid and uses no T1w
coregistration: a cheap, prior-only placement (translation + per-axis scale
from brainmask centroid/extent, no iterative registration) drops the
Harvard-Oxford lateral-ventricle prior into native space, then a local
darker-than-surroundings threshold detects what (if anything) actually looks
like ventricle in each metabolite's own raw signal.

The darkness of the detected region is deliberately not used as a score: the
detector always finds the darkest nearby voxels, and a damaged map has more of
them, so that ratio inverts direction on real data (see
experiments/native_space_ventricle_qc.py). Each detection is scored instead by
its Dice overlap with the subject's own ventricles, SynthSeg lateral
ventricles moved into MRSI space through the MRSI->T1w transform. On a 7T
motion pilot (4 subjects, still vs. moving) this overlap separated every still
scan from every moving scan for each of 11 metabolites (median-metabolite Dice
0.154-0.248 still, 0.000-0.101 moving), which is where :data:`DICE_GOOD` (0.15)
comes from: it falls between the lowest still and the highest moving median.

Typical use outside the pipeline::

    from mrsiprep.qc.ventricles import run_ventricle_qc
    result = run_ventricle_qc({"CrPCr": cr_map, "Glu": glu_map}, reference_ventricles=mask)
    result.median_dice, result.passed
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Harvard-Oxford subcortical atlas channels of the left and right lateral ventricles.
_LEFT_LATERAL_VENTRICLE_IDX = 2
_RIGHT_LATERAL_VENTRICLE_IDX = 13
_HO_ATLAS_RELATIVE = Path("data/atlases/HarvardOxford/HarvardOxford-sub-prob-2mm.nii.gz")
_MNI_BRAIN_MASK_RELATIVE = Path("data/standard/MNI152_T1_2mm_brain_mask.nii.gz")
# SynthSeg / FreeSurfer aseg labels of the left and right lateral ventricles.
SYNTHSEG_LATERAL_VENTRICLE_LABELS = (4, 43)
# Median Dice at or above this counts as "ventricles resolved" (see the module
# docstring for where the value comes from).
DICE_GOOD = 0.15


@dataclass
class MetaboliteVentricles:
    """Detection result for one metabolite map, on its canonical-oriented grid."""

    metabolite: str
    signal: np.ndarray
    prior: np.ndarray
    detected: np.ndarray
    brainmask: np.ndarray


@dataclass
class VentricleDice:
    """Overlap of one metabolite's detection with the subject's ventricles."""

    metabolite: str
    dice: float
    n_detected: int
    n_reference: int


@dataclass
class VentricleQC:
    """Detections for every metabolite, plus Dice scores when a reference was given."""

    detections: list[MetaboliteVentricles] = field(default_factory=list)
    dice: list[VentricleDice] = field(default_factory=list)

    @property
    def median_dice(self) -> float | None:
        return float(np.median([d.dice for d in self.dice])) if self.dice else None

    @property
    def passed(self) -> bool | None:
        """Median Dice at or above :data:`DICE_GOOD`; None without a reference."""
        median = self.median_dice
        return None if median is None else median >= DICE_GOOD


def _fsl_standard_path(relative: Path) -> Path | None:
    fsl_dir = os.environ.get("FSLDIR")
    if not fsl_dir:
        return None
    candidate = Path(fsl_dir) / relative
    return candidate if candidate.exists() else None


def load_canonical(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load a volume reoriented to the closest canonical (RAS) axes; 4-D -> first frame."""
    import nibabel as nib

    img = nib.as_closest_canonical(nib.load(str(path)))
    data = np.asarray(img.get_fdata())
    if data.ndim == 4:
        data = data[..., 0]
    return data, img.affine


def lateral_ventricle_prior() -> tuple[np.ndarray, np.ndarray] | None:
    """Combined left+right lateral-ventricle probability (0-100), from
    FSL's Harvard-Oxford subcortical atlas. Returns None if FSLDIR or the
    atlas data isn't available, so callers can skip this QC gracefully
    rather than fail the whole run over an optional check.
    """
    atlas_path = _fsl_standard_path(_HO_ATLAS_RELATIVE)
    if atlas_path is None:
        return None
    import nibabel as nib

    img = nib.as_closest_canonical(nib.load(str(atlas_path)))
    data = np.asarray(img.get_fdata())
    combined = np.clip(data[..., _LEFT_LATERAL_VENTRICLE_IDX] + data[..., _RIGHT_LATERAL_VENTRICLE_IDX], 0, 100)
    return combined, img.affine


def mni_brain_mask() -> tuple[np.ndarray, np.ndarray] | None:
    """Brain mask of the run's reference template.

    Taken from the same template the pipeline normalizes into
    (:mod:`mrsiprep.config.templates`) rather than from FSL's ``$FSLDIR``
    standard directory: FSL ships the MNI152NLin6Asym lineage, so the old
    source described a different space than the data being checked. Falls back
    to FSL's copy only if TemplateFlow cannot provide one, so the QC degrades
    rather than disappearing.
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
        data, affine = load_canonical(mask_path)
        return data > 0, affine


def _world_bbox_center_and_extent(mask: np.ndarray, affine: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import nibabel as nib

    idx = np.argwhere(mask)
    world = nib.affines.apply_affine(affine, idx)
    return world.mean(axis=0), world.max(axis=0) - world.min(axis=0)


def mni_to_native_placement(
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


def warp_prior_to_native(
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


def detect_ventricle_mask(
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


def dice(a: np.ndarray, b: np.ndarray) -> float:
    """Dice overlap of two boolean masks; 0 (not NaN) when both are empty."""
    total = int(a.sum() + b.sum())
    return float(2 * (a & b).sum() / total) if total else 0.0


def detect_ventricles(raw_maps: dict[str, Path]) -> list[MetaboliteVentricles] | None:
    """Run the prior placement and detection on every metabolite map.

    Metabolites are processed in sorted order. A map whose brain extent
    gives no valid placement is skipped; a map with a valid placement but
    nothing detected is kept (an empty detection is the result). Returns
    None when the atlas prior or the template brain mask is unavailable.
    """
    prior = lateral_ventricle_prior()
    mni_brain = mni_brain_mask()
    if prior is None or mni_brain is None:
        return None
    mni_vent_prob, mni_vent_affine = prior
    mni_mask, mni_affine = mni_brain

    detections: list[MetaboliteVentricles] = []
    for met in sorted(raw_maps):
        signal, affine = load_canonical(raw_maps[met])
        brainmask = np.isfinite(signal) & (signal > 0)
        placement = mni_to_native_placement(brainmask, affine, mni_mask, mni_affine)
        if placement is None:
            continue
        mni_center, native_center, scale = placement
        prior_roi = warp_prior_to_native(mni_vent_prob, mni_vent_affine, signal.shape, affine, mni_center, native_center, scale)
        prior_roi &= brainmask
        detected = detect_ventricle_mask(signal, prior_roi, brainmask)
        detections.append(MetaboliteVentricles(met, signal, prior_roi, detected, brainmask))
    return detections


def score_detections(detections: list[MetaboliteVentricles], reference: np.ndarray) -> list[VentricleDice]:
    """Dice of each detection with a reference ventricle mask on the same grid.

    The reference is restricted to each map's own brainmask, so voxels a map
    does not cover are not counted against it. Maps on a different grid than
    the reference are skipped.
    """
    scores = []
    for det in detections:
        if reference.shape != det.signal.shape:
            continue
        ref = reference & det.brainmask
        scores.append(VentricleDice(det.metabolite, dice(det.detected, ref), int(det.detected.sum()), int(ref.sum())))
    return scores


def run_ventricle_qc(raw_maps: dict[str, Path], reference_ventricles: Path | None = None) -> VentricleQC | None:
    """Detect ventricles in every metabolite map and, given the subject's own
    ventricles as a mask on the same native grid (see
    :func:`ventricle_reference_mask`), score each detection by Dice.
    Returns None when the atlas prior or template brain mask is unavailable.
    """
    detections = detect_ventricles(raw_maps)
    if detections is None:
        return None
    result = VentricleQC(detections=detections)
    if reference_ventricles is not None and Path(reference_ventricles).exists():
        result.dice = score_detections(detections, load_canonical(reference_ventricles)[0] > 0.5)
    return result


def resample_reference_ventricles(
    labels: np.ndarray, t1_img, mrsi_reference: Path, t1_to_mrsi: list[Path], out_path: Path, scratch_dir: Path, threads: int | None = None
) -> Path:
    """SynthSeg lateral ventricles on the native MRSI grid, from explicit inputs.

    ``labels`` is a SynthSeg label array on ``t1_img``'s grid. The left + right
    lateral-ventricle labels become a binary T1w-space mask, resampled through
    ``t1_to_mrsi`` (the inverse MRSI->T1w transform) with linear interpolation
    and thresholded at 0.5. Intermediate files go to ``scratch_dir``.
    """
    import nibabel as nib

    from mrsiprep.registration.transforms import apply_image_transform
    from mrsiprep.utils.images import save_nifti

    scratch_dir.mkdir(parents=True, exist_ok=True)
    t1_mask = scratch_dir / "latvent_space-T1w_mask.nii.gz"
    fraction = scratch_dir / "latvent_space-mrsi_probseg.nii.gz"
    save_nifti(np.isin(labels, SYNTHSEG_LATERAL_VENTRICLE_LABELS).astype(np.uint8), t1_img, t1_mask, dtype=np.uint8)
    apply_image_transform(mrsi_reference, t1_mask, t1_to_mrsi, fraction, interpolation="linear", threads=threads)
    frac_img = nib.load(str(fraction))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_nifti(np.asarray(frac_img.dataobj) > 0.5, frac_img, out_path, dtype=np.uint8)
    return out_path


def ventricle_reference_mask(config, subject: str, session: str | None, raw_t1: Path, mrsi_reference: Path, t1_to_mrsi: list[Path]) -> Path | None:
    """Pipeline wrapper around :func:`resample_reference_ventricles`.

    Loads the run's cached SynthSeg labels and writes the result as the
    ``space-mrsi_label-latvent_mask`` confound (reused on later runs unless
    ``--overwrite``). Returns None, so the caller simply omits the Dice
    scores, when no SynthSeg labels or transform exist (e.g. the CAT12
    tissue backend).
    """
    if not t1_to_mrsi or raw_t1 is None or mrsi_reference is None:
        return None
    import nibabel as nib

    from mrsiprep.io.naming import mrsi_derivative, resampling_work_path
    from mrsiprep.tissue.synthseg_fast import run_or_load_synthseg_labels

    out = mrsi_derivative(config.derivative_dir, subject, session, space="mrsi", label="latvent", suffix_override="mask")
    if out.exists() and not getattr(config, "overwrite", False):
        return out
    try:
        labels = run_or_load_synthseg_labels(config, subject, session, raw_t1)
    except (FileNotFoundError, RuntimeError, OSError):
        return None
    scratch = resampling_work_path(config.work_dir, subject, session, label="latvent", suffix_override="mask").parent
    return resample_reference_ventricles(
        labels, nib.load(str(raw_t1)), mrsi_reference, t1_to_mrsi, out, scratch, threads=getattr(config, "nthreads", None)
    )


def write_ventricle_qc_tsv(result: VentricleQC, out_path: Path) -> Path:
    """One row per metabolite (Dice, detected and reference voxel counts) plus a median row."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["metabolite", "dice", "n_detected", "n_reference"])
        for row in result.dice:
            writer.writerow([row.metabolite, round(row.dice, 4), row.n_detected, row.n_reference])
        if result.dice:
            writer.writerow(["median", round(result.median_dice, 4), "", ""])
    return out_path

"""Tissue workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import nibabel as nib

from mrsiprep.io.naming import anat_derivative
from mrsiprep.tissue.fractions import copy_tissue_to_derivatives, load_existing_cat12, resample_tissue_to_mrsi
from mrsiprep.tissue.fuzzy_cmeans import fuzzy_cmeans_segment
from mrsiprep.tissue.psf import resample_tissue_to_mrsi_psf
from mrsiprep.tissue.synthseg_fast import segment_t1_synthseg_fast
from mrsiprep.utils.images import load_3d_data, save_nifti


@dataclass
class TissueResult:
    """GM/WM/CSF probability maps in T1w and MRSI space, from :func:`run_tissue_workflow`.

    :ivar t1: T1w-space tissue probability maps, keyed by label
        (``"GM"``, ``"WM"``, ``"CSF"``).
    :ivar mrsi: The same tissue classes, resampled onto the MRSI grid.
    """

    t1: dict[str, Path]
    mrsi: dict[str, Path]


def segment_t1_fuzzy_cmeans(config, subject: str, session: str | None, t1_path: Path, brain_mask_path: Path) -> dict[str, Path]:
    """MIDAS-mode tissue segmentation: fuzzy c-means on a brain-extracted T1w.

    Writes GM/WM/CSF probseg NIfTIs using the same ``anat_derivative`` naming
    as ``segment_t1_synthseg_fast``, so downstream consumers need no changes.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param t1_path: Skull-stripped T1w image to segment.
    :param brain_mask_path: Brain mask matching ``t1_path``, thresholded
        at 0.5 to select voxels the c-means clustering runs over.
    :returns: Dict of ``{"GM": path, "WM": path, "CSF": path}``, skipped
        (returned as-is) if all three already exist and neither
        ``config.overwrite_seg`` nor ``config.overwrite`` is set.
    """
    outputs = {
        label: anat_derivative(config.derivative_dir, subject, session, space="T1w", label=label, suffix_override="probseg")
        for label in ("GM", "WM", "CSF")
    }
    if all(path.exists() for path in outputs.values()) and not (config.overwrite_seg or config.overwrite):
        return outputs

    t1_img, t1_data = load_3d_data(t1_path, dtype="float32", label="T1w")
    brain_mask = load_3d_data(brain_mask_path, dtype="float32", label="brain mask")[1] > 0.5
    tissue = fuzzy_cmeans_segment(t1_data, brain_mask)
    for label, data in tissue.items():
        outputs[label] = save_nifti(data.astype("float32"), t1_img, outputs[label], dtype="float32")
    return outputs


def run_tissue_workflow(
    config,
    subject: str,
    session: str | None,
    t1_path: Path,
    brain_mask: Path | None,
    mrsi_reference: Path,
    t1_to_mrsi_transforms: list[Path],
    precomputed_tissue_t1: dict[str, Path] | None = None,
) -> TissueResult:
    """Segment tissue class probabilities in T1w space and resample to MRSI space.

    T1w-space segmentation is selected via ``config.tissue_backend``:
    ``"synthseg-fast"`` runs SynthSeg + FSL FAST, ``"existing"`` reuses a
    precomputed CAT12 segmentation found in the BIDS layout. Resampling
    to MRSI space uses PSF convolution (matching the MRSI acquisition's
    point-spread function) when ``config.processing_mode == "midas"`` --
    following Maudsley et al. 2006 -- and plain transform-based resampling
    otherwise.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param t1_path: Skull-stripped T1w image to segment (ignored if
        ``precomputed_tissue_t1`` is given).
    :param brain_mask: T1w-space brain mask; may be ``None`` depending on backend.
    :param mrsi_reference: Reference-metabolite image defining the target
        MRSI grid for resampling.
    :param t1_to_mrsi_transforms: Inverse (T1w→MRSI) transform chain, as
        produced by :attr:`mrsiprep.workflows.registration.RegistrationResult.mrsi_to_t1`'s
        ``inverse``.
    :param precomputed_tissue_t1: If given, skip T1w-space segmentation
        entirely and resample these maps directly -- used when a
        subject-template longitudinal run already computed them once.
    :returns: :class:`TissueResult` with T1w- and MRSI-space GM/WM/CSF maps.
    :raises ValueError: If ``config.tissue_backend`` isn't one of the
        supported values.
    """
    backend = config.tissue_backend
    if precomputed_tissue_t1 is not None:
        tissue_t1 = precomputed_tissue_t1
    elif backend == "existing":
        tissue_t1 = copy_tissue_to_derivatives(config, subject, session, load_existing_cat12(config, subject, session))
    elif backend == "synthseg-fast":
        tissue_t1 = segment_t1_synthseg_fast(config, subject, session, t1_path)
    else:
        raise ValueError(f"Unsupported tissue backend: {backend}")
    if config.processing_mode == "midas":
        tissue_mrsi = resample_tissue_to_mrsi_psf(config, subject, session, tissue_t1, mrsi_reference, t1_to_mrsi_transforms)
    else:
        tissue_mrsi = resample_tissue_to_mrsi(config, subject, session, tissue_t1, mrsi_reference, t1_to_mrsi_transforms)
    return TissueResult(t1=tissue_t1, mrsi=tissue_mrsi)

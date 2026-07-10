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
    t1: dict[str, Path]
    mrsi: dict[str, Path]


def segment_t1_fuzzy_cmeans(config, subject: str, session: str | None, t1_path: Path, brain_mask_path: Path) -> dict[str, Path]:
    """MIDAS-mode tissue segmentation: fuzzy c-means on a brain-extracted T1w.

    Writes GM/WM/CSF probseg NIfTIs using the same ``anat_derivative`` naming
    as ``segment_t1_synthseg_fast``, so downstream consumers need no changes.
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

"""Tissue workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.tissue.fractions import copy_tissue_to_derivatives, load_existing_cat12, resample_tissue_to_mrsi
from mrsiprep.tissue.synthseg_fast import segment_t1_synthseg_fast


@dataclass
class TissueResult:
    t1: dict[str, Path]
    mrsi: dict[str, Path]


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
    tissue_mrsi = resample_tissue_to_mrsi(config, subject, session, tissue_t1, mrsi_reference, t1_to_mrsi_transforms)
    return TissueResult(t1=tissue_t1, mrsi=tissue_mrsi)

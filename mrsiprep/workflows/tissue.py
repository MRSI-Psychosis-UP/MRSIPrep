"""Tissue workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.tissue.fractions import copy_tissue_to_derivatives, load_existing_cat12, resample_tissue_to_mrsi
from mrsiprep.tissue.synthseg_fast import segment_t1_synthseg_fast


@dataclass
class TissueResult:
    """GM/WM/CSF probability maps in T1w and MRSI space, from :func:`run_tissue_workflow`.

    :ivar t1: T1w-space tissue probability maps, keyed by label
        (``"GM"``, ``"WM"``, ``"CSF"``).
    :ivar mrsi: The same tissue classes, resampled onto the MRSI grid.
    """

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
    """Segment tissue class probabilities in T1w space and resample to MRSI space.

    T1w-space segmentation is selected via ``config.tissue_backend``:
    ``"synthseg-fast"`` runs SynthSeg + FSL FAST, ``"existing"`` reuses a
    precomputed CAT12 segmentation found in the BIDS layout. Resampling
    to MRSI space uses plain transform-based resampling.

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
    tissue_mrsi = resample_tissue_to_mrsi(config, subject, session, tissue_t1, mrsi_reference, t1_to_mrsi_transforms)
    return TissueResult(t1=tissue_t1, mrsi=tissue_mrsi)

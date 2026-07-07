"""MNI atlas parcellation workflow."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.interfaces.ants import apply_transforms
from mrsiprep.io.naming import parcellation_derivative
from mrsiprep.parcellation.atlas_registry import load_mni_atlas
from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.parcellation.labels import copy_labels


def run_mni_parcellation(
    config,
    subject: str,
    session: str | None,
    mrsi_reference: Path,
    t1_reference: Path,
    mni_to_t1: list[Path],
    t1_to_mrsi: list[Path],
) -> ParcellationResult:
    atlas_path, labels_path, atlas_name = load_mni_atlas(config, config.work_dir / "atlases")
    t1_out = parcellation_derivative(config.derivative_dir, subject, session, space="T1w", atlas=atlas_name)
    mrsi_out = parcellation_derivative(config.derivative_dir, subject, session, space="MRSI", atlas=atlas_name)
    labels_out = parcellation_derivative(config.derivative_dir, subject, session, atlas=atlas_name, suffix_override="tsv")
    if not t1_out.exists() or config.overwrite:
        apply_transforms(t1_reference, atlas_path, mni_to_t1, t1_out, interpolation="genericLabel", threads=config.nthreads)
    if not mrsi_out.exists() or config.overwrite:
        apply_transforms(mrsi_reference, t1_out, t1_to_mrsi, mrsi_out, interpolation="genericLabel", threads=config.nthreads)
    copy_labels(labels_path, labels_out)
    return ParcellationResult(atlas_mni=atlas_path, atlas_t1=t1_out, atlas_mrsi=mrsi_out, labels=labels_out, mode="mni", atlas_name=atlas_name)

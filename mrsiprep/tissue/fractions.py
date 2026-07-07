"""Tissue fraction map helpers."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.interfaces.ants import apply_transforms
from mrsiprep.io.bids import BIDSLayout
from mrsiprep.io.naming import anat_derivative, mrsi_derivative


def load_existing_cat12(config, subject: str, session: str | None) -> dict[str, Path]:
    layout = BIDSLayout(config.bids_dir)
    paths = {
        "GM": layout.cat12_probseg(subject, session, 1),
        "WM": layout.cat12_probseg(subject, session, 2),
        "CSF": layout.cat12_probseg(subject, session, 3),
    }
    missing = [label for label, path in paths.items() if path is None or not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing existing tissue maps: {', '.join(missing)}")
    return {label: path for label, path in paths.items() if path is not None}


def copy_tissue_to_derivatives(config, subject: str, session: str | None, tissue_t1: dict[str, Path]) -> dict[str, Path]:
    import nibabel as nib

    from mrsiprep.utils.images import save_nifti

    out: dict[str, Path] = {}
    for label, path in tissue_t1.items():
        target = anat_derivative(config.derivative_dir, subject, session, space="T1w", label=label, suffix_override="probseg")
        if target.exists() and not (config.overwrite_seg or config.overwrite):
            out[label] = target
            continue
        img = nib.load(str(path))
        out[label] = save_nifti(img.get_fdata().astype("float32"), img, target, dtype="float32")
    return out


def resample_tissue_to_mrsi(config, subject: str, session: str | None, tissue_t1: dict[str, Path], mrsi_reference: Path, t1_to_mrsi_transforms: list[Path]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for label, path in tissue_t1.items():
        target = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", label=label, suffix_override="probseg")
        if target.exists() and not (config.overwrite_seg or config.overwrite):
            out[label] = target
            continue
        out[label] = apply_transforms(mrsi_reference, path, t1_to_mrsi_transforms, target, interpolation="linear")
    return out

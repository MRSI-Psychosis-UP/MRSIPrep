"""Anatomical preparation workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.io.bids import BIDSLayout
from mrsiprep.io.naming import anat_derivative


@dataclass
class AnatomicalResult:
    t1w: Path
    raw_t1w: Path | None
    brain_mask: Path | None
    registration_t1w: Path
    registration_mask: Path | None
    target_kind: str


def prepare_anatomical(
    config,
    subject: str,
    session: str | None,
    t1_path: Path,
    p3_override: Path | None = None,
    brain_mask_override: Path | None = None,
) -> AnatomicalResult:
    layout = BIDSLayout(config.bids_dir)
    raw_t1 = layout.raw_t1(subject, session)
    brain_mask = brain_mask_override or layout.brain_mask(subject, session)
    registration_t1 = t1_path
    registration_mask = brain_mask
    target_kind = config.registration_t1_target

    if target_kind == "brain-csf":
        p3 = p3_override or layout.cat12_probseg(subject, session, 3)
        if not p3:
            raise FileNotFoundError(
                f"Missing p3 CSF map required for brain-csf target: sub-{subject} ses-{session}"
            )
        if raw_t1 is None:
            raise FileNotFoundError(
                f"Missing raw T1w acquisition required for brain-csf target: sub-{subject} ses-{session}"
            )
        registration_t1, registration_mask = create_brain_csf_t1(
            skull_t1=t1_path,
            raw_t1=raw_t1,
            p3=p3,
            out_t1=anat_derivative(config.derivative_dir, subject, session, space="T1w", desc="brainCSF"),
            out_mask=anat_derivative(config.derivative_dir, subject, session, space="T1w", desc="brainCSFmask", suffix_override="mask"),
            threshold=config.csf_pv_threshold,
            overwrite=config.overwrite_t1_reg or config.overwrite,
        )
    elif target_kind == "raw":
        if raw_t1 is None:
            raise FileNotFoundError(f"Missing raw T1w acquisition for raw registration target: sub-{subject} ses-{session}")
        registration_t1 = raw_t1
        registration_mask = None
    elif target_kind == "brain":
        registration_t1 = t1_path
    else:
        raise ValueError(f"Unsupported registration target: {target_kind}")

    return AnatomicalResult(t1w=t1_path, raw_t1w=raw_t1, brain_mask=brain_mask, registration_t1w=registration_t1, registration_mask=registration_mask, target_kind=target_kind)


def create_brain_csf_t1(skull_t1: Path, raw_t1: Path, p3: Path, out_t1: Path, out_mask: Path, threshold: float = 0.95, overwrite: bool = False) -> tuple[Path, Path]:
    if out_t1.exists() and out_mask.exists() and not overwrite:
        return out_t1, out_mask

    skull_img = nib.load(str(skull_t1))
    raw_img = nib.load(str(raw_t1))
    p3_img = nib.load(str(p3))
    if skull_img.shape[:3] != raw_img.shape[:3] or skull_img.shape[:3] != p3_img.shape[:3]:
        raise ValueError(
            "Cannot create brainCSF T1: skull-stripped T1, raw T1, and p3 have different shapes."
        )
    if not (np.allclose(skull_img.affine, raw_img.affine, atol=1e-3) and np.allclose(skull_img.affine, p3_img.affine, atol=1e-3)):
        raise ValueError(
            "Cannot create brainCSF T1: skull-stripped T1, raw T1, and p3 do not share the same affine."
        )
    skull = np.nan_to_num(skull_img.get_fdata(dtype=np.float32).squeeze(), copy=False)
    raw = np.nan_to_num(raw_img.get_fdata(dtype=np.float32).squeeze(), copy=False)
    p3_data = np.nan_to_num(p3_img.get_fdata(dtype=np.float32).squeeze(), copy=False)
    brain_mask = skull > 0
    csf_mask = (p3_data > threshold) & ~brain_mask
    extended = skull.copy()
    extended[csf_mask] = skull[csf_mask] + raw[csf_mask]
    mask = (brain_mask | csf_mask).astype(np.uint8)

    out_t1.parent.mkdir(parents=True, exist_ok=True)
    header = skull_img.header.copy()
    header.set_data_dtype(np.float32)
    out_img = nib.Nifti1Image(extended.astype(np.float32), skull_img.affine, header)
    out_img.set_qform(skull_img.affine, code=int(skull_img.header["qform_code"]))
    out_img.set_sform(skull_img.affine, code=int(skull_img.header["sform_code"]))
    nib.save(out_img, str(out_t1))

    mask_header = skull_img.header.copy()
    mask_header.set_data_dtype(np.uint8)
    nib.save(nib.Nifti1Image(mask, skull_img.affine, mask_header), str(out_mask))
    saved = nib.load(str(out_t1)).get_fdata(dtype=np.float32).squeeze()
    unchanged = ~csf_mask
    if np.max(np.abs(saved[unchanged] - skull[unchanged])) > 1e-3:
        raise RuntimeError("Saved brainCSF T1 changed voxels outside the added CSF mask.")
    return out_t1, out_mask

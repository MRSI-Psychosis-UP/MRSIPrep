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
    """T1w images/masks selected for registration, from :func:`prepare_anatomical`.

    :ivar t1w: The skull-stripped T1w passed in as ``t1_path`` (SynthSeg
        or CAT12 brain extraction output, depending on ``config.tissue_backend``).
    :ivar raw_t1w: The original, non-skull-stripped T1w acquisition, if
        found in the BIDS layout; ``None`` if the dataset only provides a
        pre-skull-stripped image.
    :ivar brain_mask: Brain-only mask corresponding to ``t1w``, if available.
    :ivar registration_t1w: The T1w image registration should actually
        target -- equal to ``t1w`` for the ``brain`` target, ``raw_t1w``
        for ``raw``, or a freshly built brain+CSF composite for ``brain-csf``.
    :ivar registration_mask: Mask matching ``registration_t1w`` (``None``
        for the ``raw`` target, which registers without a fixed mask).
    :ivar target_kind: The resolved ``config.registration_t1_target``
        value (``"brain"``, ``"brain-csf"``, or ``"raw"``).
    """

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
    """Resolve which T1w image/mask registration should target.

    Dispatches on ``config.registration_t1_target``:

    - ``"brain"`` -- register directly to the skull-stripped ``t1_path``
      (the common case).
    - ``"brain-csf"`` -- build a fresh T1w with the CSF compartment
      re-added to the skull-stripped image (via :func:`create_brain_csf_t1`,
      using the CAT12 p3 CSF probability map), so CSF-adjacent MRSI
      signal isn't clipped at the brain-only boundary. Requires both a
      raw T1w acquisition and a p3 map to be found in the BIDS layout.
    - ``"raw"`` -- register to the original, non-skull-stripped T1w with
      no fixed mask.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param t1_path: Skull-stripped T1w image (SynthSeg/CAT12 brain
        extraction output).
    :param p3_override: Explicit CAT12 p3 CSF probseg path, bypassing
        BIDS-layout lookup; used by ``brain-csf`` when set.
    :param brain_mask_override: Explicit brain mask path, bypassing
        BIDS-layout lookup.
    :returns: :class:`AnatomicalResult` describing which image/mask pair
        downstream registration should use.
    :raises FileNotFoundError: If ``target_kind`` is ``"brain-csf"`` or
        ``"raw"`` and the required raw T1w / p3 map isn't found.
    :raises ValueError: If ``config.registration_t1_target`` isn't one of
        the three supported values.
    """
    layout = BIDSLayout.from_config(config)
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
    """Re-add the CSF compartment to a skull-stripped T1w for the ``brain-csf`` registration target.

    Combines the ``skull_t1`` brain mask with voxels where the CAT12 CSF
    probability map (``p3``) exceeds ``threshold``, then masks ``raw_t1``
    with the union -- so CSF-adjacent MRSI signal isn't clipped at the
    brain-only boundary. ``skull_t1``, ``raw_t1``, and ``p3`` must share
    the same shape and affine.

    :param skull_t1: Skull-stripped T1w (defines the brain-only mask via
        ``> 0``).
    :param raw_t1: Original, non-skull-stripped T1w acquisition -- only
        its CSF-region voxels are used.
    :param p3: CAT12 CSF tissue-probability map, same grid as ``skull_t1``.
    :param out_t1: Output path for the brain+CSF composite T1w.
    :param out_mask: Output path for the corresponding brain+CSF binary mask.
    :param threshold: Minimum CSF probability (in ``p3``) for a voxel
        outside the brain mask to be classified as CSF and included.
    :param overwrite: Recompute even if ``out_t1``/``out_mask`` already exist.
    :returns: ``(out_t1, out_mask)``.
    :raises ValueError: If the three input images don't share a shape or affine.
    """
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

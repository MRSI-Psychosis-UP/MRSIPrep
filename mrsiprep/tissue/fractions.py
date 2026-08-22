"""Tissue fraction map helpers."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.bids import BIDSLayout
from mrsiprep.io.naming import anat_derivative, mrsi_derivative
from mrsiprep.registration.transforms import apply_image_transform


def load_existing_cat12(config, subject: str, session: str | None) -> dict[str, Path]:
    """Locate pre-computed CAT12 GM/WM/CSF tissue-probability maps for a recording.

    Used by the ``existing`` :attr:`~mrsiprep.config.settings.MRSIPrepConfig.tissue_backend`,
    which reuses tissue segmentation already produced outside MRSIPrep instead
    of running SynthSeg+FAST.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :returns: ``{"GM": path, "WM": path, "CSF": path}``, the CAT12 p1/p2/p3
        probability-segmentation files found in the BIDS layout.
    :raises FileNotFoundError: If any of the three maps is missing.
    """
    layout = BIDSLayout.from_config(config)
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
    """Copy T1w-space tissue-probability maps into the MRSIPrep derivatives tree.

    Used with the ``existing`` tissue backend to bring CAT12 maps (found
    wherever :func:`load_existing_cat12` located them) under MRSIPrep's own
    ``confounds/`` output naming, alongside SynthSeg+FAST-produced maps.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param tissue_t1: ``{label: path}`` of T1w-space tissue-probability maps
        to copy, keyed by tissue label (e.g. ``"GM"``, ``"WM"``, ``"CSF"``).
    :returns: ``{label: path}`` of the copied files' derivative paths.
        Recordings already copied are skipped (returned as-is) unless
        ``config.overwrite_seg``/``config.overwrite`` is set.
    """
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
    """Resample T1w-space tissue-probability maps onto the native MRSI grid.

    Plain linear-interpolation resample, applying the (inverse) MRSI-to-T1w
    transform to bring each map back onto ``mrsi_reference``'s grid for use
    in partial-volume correction.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param tissue_t1: ``{label: path}`` of T1w-space tissue-probability maps
        to resample.
    :param mrsi_reference: MRSI reference image defining the target grid.
    :param t1_to_mrsi_transforms: Ordered ANTs/FSL transform file(s) mapping
        T1w space to MRSI space (i.e. the inverse of the MRSI-to-T1w
        registration).
    :returns: ``{label: path}`` of the resampled, MRSI-grid tissue-probability
        maps. Recordings already resampled are skipped (returned as-is)
        unless ``config.overwrite_seg``/``config.overwrite`` is set.
    """
    out: dict[str, Path] = {}
    for label, path in tissue_t1.items():
        target = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", label=label, suffix_override="probseg")
        if target.exists() and not (config.overwrite_seg or config.overwrite):
            out[label] = target
            continue
        out[label] = apply_image_transform(mrsi_reference, path, t1_to_mrsi_transforms, target, interpolation="linear", threads=config.nthreads)
    return out

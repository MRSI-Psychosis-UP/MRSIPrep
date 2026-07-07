"""SynthSeg-constrained FSL FAST tissue backend."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import nibabel as nib
import numpy as np
from nibabel.processing import resample_from_to
from mrsiprep.interfaces.fsl import run_fast
from mrsiprep.io.naming import anat_derivative
from mrsiprep.utils.images import save_nifti
from mrsiprep.utils.subprocess_utils import run_checked


VENTRICLE_LABELS = {4, 5, 14, 15, 43, 44}
OUTER_CSF_LABEL = 24
CSF_VENTRICLE_LABELS = {*VENTRICLE_LABELS, OUTER_CSF_LABEL}


def synthseg_fast_csf_probseg_path(config, subject: str, session: str | None) -> Path:
    return anat_derivative(config.derivative_dir, subject, session, space="T1w", label="CSF", suffix_override="probseg")


def synthseg_fast_brain_path(config, subject: str, session: str | None) -> Path:
    return anat_derivative(config.derivative_dir, subject, session, space="T1w", desc="synthsegBrain")


def synthseg_fast_brain_mask_path(config, subject: str, session: str | None) -> Path:
    return anat_derivative(config.derivative_dir, subject, session, space="T1w", desc="synthsegBrain", suffix_override="mask")


def synthseg_work_dir(config, subject: str, session: str | None) -> Path:
    return config.work_dir / f"sub-{subject}" / (f"ses-{session}" if session else "ses-none") / "synthseg_fast"


def synthseg_native_labels_path(config, subject: str, session: str | None) -> Path:
    mode = getattr(config, "synthseg_mode", "fast")
    return anat_derivative(config.derivative_dir, subject, session, space="T1w", desc=f"synthsegParc{mode.capitalize()}", suffix_override="dseg")


def synthseg_fast_input_path(config, subject: str, session: str | None) -> Path:
    return anat_derivative(config.derivative_dir, subject, session, space="T1w", desc="synthsegFastInput")


def run_or_load_synthseg_labels(config, subject: str, session: str | None, t1_path: Path) -> np.ndarray:
    work_dir = synthseg_work_dir(config, subject, session)
    work_dir.mkdir(parents=True, exist_ok=True)
    return _run_or_load_synthseg(config, Path(t1_path), work_dir, subject, session)


def segment_t1_synthseg_fast(config, subject: str, session: str | None, t1_path: Path) -> dict[str, Path]:
    """Segment GM/WM/CSF with SynthSeg-constrained FAST.

    SynthSeg supplies the brain/CSF mask and anatomical labels. FAST runs only
    inside that mask and supplies the partial-volume estimates.
    """

    t1_path = Path(t1_path)
    work_dir = synthseg_work_dir(config, subject, session)
    work_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        label: anat_derivative(
            config.derivative_dir,
            subject,
            session,
            space="T1w",
            label=label,
            suffix_override="probseg",
        )
        for label in ("GM", "WM", "CSF")
    }
    brain_out = synthseg_fast_brain_path(config, subject, session)
    brain_mask_out = synthseg_fast_brain_mask_path(config, subject, session)
    if all(path.exists() for path in [*outputs.values(), brain_out, brain_mask_out]) and not (config.overwrite_seg or config.overwrite):
        return outputs

    t1_img = nib.load(str(t1_path))
    labels_native = _run_or_load_synthseg(config, t1_path, work_dir, subject, session)
    fast_mask = _write_synthseg_brain(
        config,
        t1_img,
        labels_native,
        brain_out,
        brain_mask_out,
    )
    masked_t1 = _write_masked_t1(t1_img, fast_mask, synthseg_fast_input_path(config, subject, session))

    fast_sources = run_fast(masked_t1, work_dir / "fast" / "fast", verbose=config.verbose >= 3)
    fast_maps = {}
    for label, source in fast_sources.items():
        img = nib.load(str(source))
        fast_maps[label] = np.clip(np.nan_to_num(img.get_fdata(dtype=np.float32).squeeze(), copy=False), 0.0, 1.0)
    fast_maps = _apply_synthseg_csf_tissue_correction(fast_maps, labels_native)
    for label, data in fast_maps.items():
        outputs[label] = save_nifti(data, t1_img, outputs[label], dtype=np.float32)
    return outputs


def extract_t1_synthseg(config, subject: str, session: str | None, t1_path: Path) -> tuple[Path, Path]:
    """Create a SynthSeg-masked T1w and binary mask without running FAST."""

    t1_path = Path(t1_path)
    work_dir = synthseg_work_dir(config, subject, session)
    work_dir.mkdir(parents=True, exist_ok=True)
    brain_out = synthseg_fast_brain_path(config, subject, session)
    mask_out = synthseg_fast_brain_mask_path(config, subject, session)
    if brain_out.exists() and mask_out.exists() and not (config.overwrite_seg or config.overwrite):
        return brain_out, mask_out

    t1_img = nib.load(str(t1_path))
    labels = _run_or_load_synthseg(config, t1_path, work_dir, subject, session)
    _write_synthseg_brain(config, t1_img, labels, brain_out, mask_out)
    return brain_out, mask_out


def _run_or_load_synthseg(config, t1_path: Path, work_dir: Path, subject: str, session: str | None) -> np.ndarray:
    mode = getattr(config, "synthseg_mode", "fast")
    native_labels = synthseg_native_labels_path(config, subject, session)
    if native_labels.exists() and not (config.overwrite_seg or config.overwrite):
        return _load_labels(native_labels)

    synthseg_labels = work_dir / f"synthseg_parc-{mode}_labels.nii.gz"
    if not synthseg_labels.exists() or config.overwrite_seg or config.overwrite:
        synthseg_cmd = _find_mri_synthseg()
        command = _synthseg_command(config, synthseg_cmd, t1_path, synthseg_labels)
        run_checked(command, verbose=config.verbose >= 3, env=_synthseg_env(synthseg_cmd), error_prefix="mri_synthseg")

    labels_img = nib.load(str(synthseg_labels))
    t1_img = nib.load(str(t1_path))
    if labels_img.shape[:3] != t1_img.shape[:3] or not np.allclose(labels_img.affine, t1_img.affine, atol=1e-3):
        labels_img = resample_from_to(labels_img, (t1_img.shape[:3], t1_img.affine), order=0)
    labels = np.rint(np.nan_to_num(labels_img.get_fdata(dtype=np.float32).squeeze(), copy=False)).astype(np.uint16)
    save_nifti(labels, t1_img, native_labels, dtype=np.uint16)
    return labels


def _synthseg_command(config, executable: str, t1_path: Path, out_path: Path) -> list[str]:
    mode = getattr(config, "synthseg_mode", "fast")
    command = [
        executable,
        "--i",
        str(t1_path),
        "--o",
        str(out_path),
        "--parc",
        "--threads",
        str(config.nthreads),
        "--cpu",
    ]
    if mode == "fast":
        command.append("--fast")
    elif mode == "robust":
        command.append("--robust")
    return command


def _synthseg_brain_mask(labels: np.ndarray) -> np.ndarray:
    return np.asarray(labels) != 0


def _write_synthseg_brain(
    config,
    t1_img: nib.Nifti1Image,
    labels: np.ndarray,
    brain_out: Path,
    mask_out: Path,
) -> np.ndarray:
    mask = _synthseg_brain_mask(labels)
    _write_masked_t1(t1_img, mask, brain_out)
    save_nifti(mask.astype(np.uint8), t1_img, mask_out, dtype=np.uint8)
    return mask


def _synthseg_csf_ventricle_mask(labels: np.ndarray) -> np.ndarray:
    return np.isin(np.asarray(labels), list(CSF_VENTRICLE_LABELS))


def _apply_synthseg_csf_tissue_correction(fast_maps: dict[str, np.ndarray], labels: np.ndarray) -> dict[str, np.ndarray]:
    corrected = {label: data.copy() for label, data in fast_maps.items()}
    synthseg_labels = np.asarray(labels)
    synthseg_background = synthseg_labels == 0
    if np.any(synthseg_background):
        for label in ("GM", "WM", "CSF"):
            corrected[label][synthseg_background] = 0.0

    synthseg_csf = _synthseg_csf_ventricle_mask(synthseg_labels)
    tissue_in_synthseg_csf = synthseg_csf & ((corrected["GM"] > 0.01) | (corrected["WM"] > 0.01))
    if np.any(tissue_in_synthseg_csf):
        corrected["GM"][tissue_in_synthseg_csf] = 0.0
        corrected["WM"][tissue_in_synthseg_csf] = 0.0
        corrected["CSF"][tissue_in_synthseg_csf] = 1.0
    return corrected


def _write_masked_t1(t1_img: nib.Nifti1Image, mask: np.ndarray, out_path: Path) -> Path:
    t1 = np.nan_to_num(t1_img.get_fdata(dtype=np.float32).squeeze(), copy=False)
    masked = np.where(mask, t1, 0.0).astype(np.float32)
    return save_nifti(masked, t1_img, out_path, dtype=np.float32)


def _load_labels(path: Path) -> np.ndarray:
    return np.rint(np.nan_to_num(nib.load(str(path)).get_fdata(dtype=np.float32).squeeze(), copy=False)).astype(np.uint16)


def _find_mri_synthseg() -> str:
    return find_freesurfer_tool("mri_synthseg")


# Relative locations of a tool within a FreeSurfer install, and the common
# roots under which a versioned FreeSurfer may live. Kept version-agnostic
# (globbed) so upgrading FreeSurfer needs no code change.
_FS_TOOL_SUBPATHS = ("bin/{tool}", "python/scripts/{tool}")
_FS_INSTALL_ROOTS = ("/usr/local/freesurfer", "/opt/freesurfer", str(Path.home() / "Apps"))


def find_freesurfer_tool(tool: str) -> str:
    """Locate a FreeSurfer tool without hardcoding a version.

    Resolution order: PATH, then ``FREESURFER_HOME`` (direct and one level of
    version subdir), then any versioned install under the common roots
    (``freesurfer-*/`` or ``*/`` subdirs), newest-looking first.
    """
    found = shutil.which(tool)
    if found:
        return found

    candidates: list[Path] = []

    fs_home = os.environ.get("FREESURFER_HOME")
    if fs_home:
        root = Path(fs_home)
        for sub in _FS_TOOL_SUBPATHS:
            candidates.append(root / sub.format(tool=tool))
            candidates.extend(sorted(root.glob(f"*/{sub.format(tool=tool)}"), reverse=True))

    for install_root in _FS_INSTALL_ROOTS:
        base = Path(install_root)
        for sub in _FS_TOOL_SUBPATHS:
            candidates.append(base / sub.format(tool=tool))
            for pattern in (f"*/{sub.format(tool=tool)}", f"freesurfer-*/*/{sub.format(tool=tool)}"):
                candidates.extend(sorted(base.glob(pattern), reverse=True))

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        f"{tool} was not found on PATH, in FREESURFER_HOME, or under {', '.join(_FS_INSTALL_ROOTS)}. "
        "Source FreeSurfer before running this step."
    )


def _synthseg_env(command: str) -> dict[str, str]:
    env = os.environ.copy()
    path = Path(command)
    if path.name == "mri_synthseg" and path.parent.name == "bin":
        fs_home = path.parent.parent
        if (fs_home / "python" / "scripts" / "mri_synthseg").exists():
            env["FREESURFER_HOME"] = str(fs_home)
    return env

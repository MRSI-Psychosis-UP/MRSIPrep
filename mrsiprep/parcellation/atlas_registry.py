"""MNI atlas loading."""

from __future__ import annotations

import os
from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.parcellation.labels import write_labels


ATLAS_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "atlas"


def _save_nifti_atomic(img, out_path: Path) -> None:
    """Write `img` to a temp file next to `out_path`, then atomically rename
    it into place -- avoids two concurrent --nproc workers racing to fetch
    and write the same shared, subject-independent atlas cache file and
    corrupting it (one worker's partial write clobbering another's)."""
    tmp_path = out_path.with_name(f".{out_path.name}.tmp-{os.getpid()}")
    nib.save(img, tmp_path)
    os.replace(tmp_path, out_path)


def load_mni_atlas(config, work_dir: str | Path) -> tuple[Path, Path, str]:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    atlas = config.atlas.lower()
    bundled = _find_bundled_atlas(atlas)
    if bundled is not None:
        return bundled
    if atlas == "custom":
        if not config.custom_atlas or not config.custom_atlas_lut:
            raise ValueError("--custom-atlas and --custom-atlas-lut are required for atlas=custom.")
        return Path(config.custom_atlas), Path(config.custom_atlas_lut), "custom"
    if atlas.startswith("schaefer"):
        atlas_path = work_dir / f"atlas-{atlas}_space-MNI152NLin2009cAsym_dseg.nii.gz"
        labels_path = work_dir / f"atlas-{atlas}_labels.tsv"
        # Same shared cache file for every subject/session (the atlas is
        # subject-independent), so a --nproc worker that finds it already
        # complete reuses it instead of re-fetching/re-resampling and racing
        # concurrent writers.
        if atlas_path.exists() and labels_path.exists():
            return atlas_path, labels_path, atlas
        from nilearn import datasets, image

        n_rois = int(atlas.replace("schaefer", ""))
        fetched = datasets.fetch_atlas_schaefer_2018(n_rois=n_rois, yeo_networks=7, resolution_mm=1)
        atlas_img = image.resample_to_img(fetched.maps, datasets.load_mni152_template(), interpolation="nearest", force_resample=True)
        _save_nifti_atomic(atlas_img, atlas_path)
        data = atlas_img.get_fdata().astype(int)
        indices = np.unique(data)
        indices = indices[indices != 0]
        labels = [label.decode() if isinstance(label, bytes) else str(label) for label in fetched.labels]
        write_labels(indices, labels[: len(indices)], labels_path)
        return atlas_path, labels_path, atlas
    if atlas in {"mist197", "mist-197"}:
        atlas_path = work_dir / "atlas-mist197_space-MNI152NLin2009cAsym_dseg.nii.gz"
        labels_path = work_dir / "atlas-mist197_labels.tsv"
        if atlas_path.exists() and labels_path.exists():
            return atlas_path, labels_path, "mist197"
        from nilearn import datasets, image

        fetched = datasets.fetch_atlas_basc_multiscale_2015()
        atlas_img = image.resample_to_img(fetched.scale197, datasets.load_mni152_template(), interpolation="nearest", force_resample=True)
        _save_nifti_atomic(atlas_img, atlas_path)
        indices = np.unique(atlas_img.get_fdata().astype(int))
        indices = indices[indices != 0]
        write_labels(indices, [f"MIST-{i}" for i in indices], labels_path)
        return atlas_path, labels_path, "mist197"
    raise ValueError(f"Unsupported MNI atlas: {config.atlas}")


def available_bundled_atlases() -> list[str]:
    if not ATLAS_DATA_DIR.exists():
        return []
    return sorted(path.name for path in ATLAS_DATA_DIR.iterdir() if path.is_dir() and list(path.glob("*.nii*")) and list(path.glob("*.tsv")))


def _find_bundled_atlas(atlas: str) -> tuple[Path, Path, str] | None:
    if not ATLAS_DATA_DIR.exists():
        return None
    requested = _atlas_key(atlas.removeprefix("bundled:"))
    for directory in ATLAS_DATA_DIR.iterdir():
        if not directory.is_dir() or _atlas_key(directory.name) != requested:
            continue
        images = sorted(directory.glob("*.nii.gz")) or sorted(directory.glob("*.nii"))
        labels = sorted(directory.glob("*.tsv"))
        if images and labels:
            return images[0], labels[0], directory.name.replace("-", "")
    return None


def _atlas_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())

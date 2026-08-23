"""MNI atlas loading."""

from __future__ import annotations

import os
from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.config.templates import template_t1w
from mrsiprep.parcellation.labels import write_labels


ATLAS_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "atlas"


def _save_nifti_atomic(img, out_path: Path) -> None:
    """Write `img` to a temp file next to `out_path`, then atomically rename
    it into place -- avoids two concurrent --nproc workers racing to fetch
    and write the same shared, subject-independent atlas cache file and
    corrupting it (one worker's partial write clobbering another's)."""
    # The pid/temp marker must come *before* the real filename, not after --
    # nib.save() infers the image format from a trailing .nii/.nii.gz/etc.
    # extension, so appending anything past it (e.g. "...nii.gz.tmp-123")
    # leaves no recognizable extension and raises ImageFileError.
    tmp_path = out_path.with_name(f".tmp-{os.getpid()}-{out_path.name}")
    nib.save(img, tmp_path)
    os.replace(tmp_path, out_path)


def load_mni_atlas(config, work_dir: str | Path, atlas_name: str | None = None) -> tuple[Path, Path, str]:
    """Resolve one MNI-space atlas to (atlas_path, labels_path, name).

    :param atlas_name: Which atlas to load. Defaults to ``config.atlas``;
        pass an explicit name when ``--atlas`` carries a comma-separated list
        so each entry resolves independently.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    atlas = (atlas_name if atlas_name is not None else config.atlas).lower()
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
        atlas_img = image.resample_to_img(fetched.maps, template_t1w(), interpolation="nearest", force_resample=True)
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
        atlas_img = image.resample_to_img(fetched.scale197, template_t1w(), interpolation="nearest", force_resample=True)
        _save_nifti_atomic(atlas_img, atlas_path)
        indices = np.unique(atlas_img.get_fdata().astype(int))
        indices = indices[indices != 0]
        write_labels(indices, [f"MIST-{i}" for i in indices], labels_path)
        return atlas_path, labels_path, "mist197"
    raise ValueError(f"Unsupported MNI atlas: {atlas}")


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
            return images[0], labels[0], _bundled_atlas_label(directory.name)
    return None


def _bundled_atlas_label(dirname: str) -> str:
    """Turn a bundled atlas directory name into a BIDS-safe entity value
    that keeps the scheme code and its trailing number unambiguously
    delimited (e.g. 'chimera-LFMIHIFIS_scale3' -> 'chimeraLFMIHIFIS_scale3').
    Bundled atlas directories already use this delimited naming; this is a
    defensive fallback for a directory name that still uses the old bare
    '<scheme>-<N>' convention (e.g. 'chimera-LFMIHIFIS-3'), which plain
    hyphen-stripping would otherwise fuse into an ambiguous
    'chimeraLFMIHIFIS3' with no separator between scheme code and number.

    'scale' is only used for schemes whose cortex position (the scheme
    code's first letter) is 'L' (Lausanne), matching --chimera-scale's own
    documented meaning; for other schemes the trailing number means
    something else (e.g. a fixed total parcel count), so it is kept
    delimited without claiming it is a scale.
    """
    parts = dirname.split("-")
    if len(parts) >= 3 and parts[-1].isdigit():
        prefix = "".join(parts[:-1])
        suffix = parts[-1]
        scheme = parts[1] if len(parts) > 2 else ""
        if scheme[:1].upper() == "L":
            return f"{prefix}_scale{suffix}"
        return f"{prefix}_{suffix}"
    return dirname.replace("-", "")


def _atlas_key(value: str) -> str:
    # Strip the literal word "scale" in addition to non-alphanumerics, so
    # both the current delimited directory naming ('chimera-LFMIHIFIS_scale3')
    # and the old bare-number style some callers/configs may still pass
    # ('chimera-LFMIHIFIS-3') normalize to the same key and still resolve to
    # the same bundled atlas.
    cleaned = "".join(character for character in value.lower() if character.isalnum())
    return cleaned.replace("scale", "")

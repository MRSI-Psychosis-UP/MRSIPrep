"""Parcel-fraction helper placeholder."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np


def hard_label_fraction_npz(atlas_mrsi: str | Path, out_path: str | Path) -> Path:
    data = nib.load(str(atlas_mrsi)).get_fdata().astype(int)
    labels = np.unique(data)
    labels = labels[labels != 0]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, labels=labels, note="Hard-label proxy fractions; soft supersampling not yet enabled.")
    return out_path

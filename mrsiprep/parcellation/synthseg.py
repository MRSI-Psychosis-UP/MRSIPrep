"""Lightweight SynthSeg cortical and subcortical parcellation."""

from __future__ import annotations

import os
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

from mrsiprep.interfaces.ants import apply_transforms
from mrsiprep.io.naming import parcellation_derivative
from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.parcellation.labels import infer_hemisphere
from mrsiprep.tissue.synthseg_fast import CSF_VENTRICLE_LABELS, run_or_load_synthseg_labels
from mrsiprep.utils.images import save_nifti


def run_synthseg_parcellation(
    config,
    subject: str,
    session: str | None,
    raw_t1: Path,
    mrsi_reference: Path,
    t1_to_mrsi: list[Path],
) -> ParcellationResult:
    """Create a GM/WM-only SynthSeg atlas in native T1 and MRSI spaces."""

    mode = getattr(config, "synthseg_mode", "fast")
    atlas_name = "synthseg"
    atlas_t1 = parcellation_derivative(
        config.derivative_dir,
        subject,
        session,
        space="T1w",
        atlas=atlas_name,
        desc=f"{mode}GMWM",
    )
    atlas_mrsi = parcellation_derivative(
        config.derivative_dir,
        subject,
        session,
        space="MRSI",
        atlas=atlas_name,
        desc=f"{mode}GMWM",
    )
    labels_out = parcellation_derivative(
        config.derivative_dir,
        subject,
        session,
        atlas=atlas_name,
        desc=f"{mode}GMWM",
        suffix_override="tsv",
    )

    labels = run_or_load_synthseg_labels(config, subject, session, raw_t1)
    retained = labels.copy()
    retained[np.isin(retained, [0, *CSF_VENTRICLE_LABELS])] = 0
    t1_img = nib.load(str(raw_t1))
    if not atlas_t1.exists() or config.overwrite:
        save_nifti(retained, t1_img, atlas_t1, dtype=np.uint16)
    if not atlas_mrsi.exists() or config.overwrite:
        apply_transforms(mrsi_reference, atlas_t1, t1_to_mrsi, atlas_mrsi, interpolation="genericLabel", threads=config.nthreads)

    indices = np.unique(retained)
    indices = indices[indices != 0]
    _write_labels(indices, labels_out)
    return ParcellationResult(
        atlas_t1=atlas_t1,
        atlas_mrsi=atlas_mrsi,
        labels=labels_out,
        mode="synthseg",
        atlas_name=atlas_name,
    )


def _write_labels(indices: np.ndarray, out_path: Path) -> Path:
    lut = _read_freesurfer_lut()
    rows = []
    for value in indices:
        parcel_id = int(value)
        name, color = lut.get(parcel_id, (f"SynthSeg-{parcel_id}", "#808080"))
        rows.append(
            {
                "parcel_id": parcel_id,
                "parcel_name": name,
                "hemisphere": infer_hemisphere(name),
                "color": color,
            }
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, sep="\t", index=False)
    return out_path


def _read_freesurfer_lut() -> dict[int, tuple[str, str]]:
    fs_home = Path(os.environ.get("FREESURFER_HOME", "/opt/freesurfer"))
    lut_path = fs_home / "FreeSurferColorLUT.txt"
    if not lut_path.exists():
        return {}
    labels: dict[int, tuple[str, str]] = {}
    for line in lut_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        fields = line.split()
        if len(fields) < 5 or not fields[0].isdigit():
            continue
        try:
            red, green, blue = (int(fields[index]) for index in (2, 3, 4))
        except ValueError:
            continue
        labels[int(fields[0])] = (fields[1], f"#{red:02x}{green:02x}{blue:02x}")
    return labels

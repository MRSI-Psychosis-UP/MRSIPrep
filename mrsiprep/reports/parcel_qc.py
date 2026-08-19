"""Parcelwise anatomical coverage and MRSI quality summaries."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.io.naming import parcellation_derivative
from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.utils.images import load_3d_data
from mrsiprep.utils.tables import read_labels, write_tsv


def write_parcel_qc(
    config,
    subject: str,
    session: str | None,
    parcels: ParcellationResult,
    mrsi_brainmask: Path,
    crlb_maps: dict[str, Path],
    qcmasks: dict[str, Path],
) -> Path:
    # Anatomical coverage is computed natively in MRSI space: atlas_mrsi is
    # already the T1w atlas warped onto the MRSI acquisition grid (same
    # shape/affine as mrsi_brainmask), so intersecting it with the brain mask
    # directly avoids resampling the (typically much larger, asymmetrically
    # padded) T1w grid, which previously made triplanar coverage figures
    # misleading regardless of slice selection.
    atlas_t1 = _labels(parcels.atlas_t1) if parcels.atlas_t1 is not None else None
    atlas_mrsi = _labels(parcels.atlas_mrsi)
    support_mrsi = load_3d_data(mrsi_brainmask, dtype=np.float32, label="MRSI brain mask")[1] > 0.5
    labels = read_labels(parcels.labels)
    crlb_data = {met: _optional_data(path) for met, path in crlb_maps.items()}
    qc_data = {met: _optional_data(path, boolean=True) for met, path in qcmasks.items()}
    metabolites = sorted(set(crlb_data) | set(qc_data)) or [""]

    rows = []
    for _, label_row in labels.iterrows():
        parcel_id = int(label_row["parcel_id"])
        mrsi_parcel = atlas_mrsi == parcel_id
        mrsi_total = int(mrsi_parcel.sum())
        mrsi_covered = int(np.count_nonzero(mrsi_parcel & support_mrsi))
        t1_total = int((atlas_t1 == parcel_id).sum()) if atlas_t1 is not None else mrsi_total
        for metabolite in metabolites:
            crlb = crlb_data.get(metabolite)
            valid_crlb = mrsi_parcel & np.isfinite(crlb) & (crlb > 0) if crlb is not None else np.zeros_like(mrsi_parcel)
            qcmask = qc_data.get(metabolite)
            qc_valid = mrsi_parcel & qcmask if qcmask is not None else valid_crlb
            rows.append(
                {
                    "subject": f"sub-{subject}",
                    "session": f"ses-{session}" if session else "",
                    "atlas": parcels.atlas_name,
                    "parcel_id": parcel_id,
                    "parcel_name": label_row.get("parcel_name", str(parcel_id)),
                    "hemisphere": label_row.get("hemisphere", "NA"),
                    "metabolite": metabolite,
                    "t1_parcel_voxels": t1_total,
                    "t1_mrsi_covered_voxels": mrsi_covered,
                    "anatomical_coverage_fraction": mrsi_covered / max(mrsi_total, 1),
                    "anatomical_coverage_percent": 100.0 * mrsi_covered / max(mrsi_total, 1),
                    "mrsi_parcel_voxels": mrsi_total,
                    "qc_valid_voxels": int(qc_valid.sum()),
                    "qc_valid_fraction": float(qc_valid.sum() / max(mrsi_total, 1)),
                    "mean_crlb": float(np.nanmean(crlb[valid_crlb])) if crlb is not None and np.any(valid_crlb) else np.nan,
                    "median_crlb": float(np.nanmedian(crlb[valid_crlb])) if crlb is not None and np.any(valid_crlb) else np.nan,
                }
            )

    out = parcellation_derivative(
        config.derivative_dir,
        subject,
        session,
        atlas=parcels.atlas_name,
        desc="parcelqc",
        suffix_override="tsv",
    )
    write_tsv(rows, out)
    return out


def _labels(path: Path) -> np.ndarray:
    return np.rint(nib.load(str(path)).get_fdata(dtype=np.float32).squeeze()).astype(np.int32)


def _optional_data(path: Path | None, boolean: bool = False):
    if path is None or not Path(path).exists():
        return None
    data = load_3d_data(path, dtype=np.float32)[1]
    return data > 0.5 if boolean else data

"""Parcelwise anatomical coverage and MRSI quality summaries."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.interfaces.ants import apply_transforms
from mrsiprep.io.naming import mrsi_derivative, parcellation_derivative
from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.utils.images import load_3d_data
from mrsiprep.utils.tables import read_labels, write_tsv


def write_parcel_qc(
    config,
    subject: str,
    session: str | None,
    parcels: ParcellationResult,
    t1_reference: Path,
    mrsi_brainmask: Path,
    mrsi_to_t1: list[Path],
    crlb_maps: dict[str, Path],
    qcmasks: dict[str, Path],
) -> Path:
    if parcels.atlas_t1 is None:
        raise ValueError(f"{parcels.mode} parcellation does not provide a T1-space atlas for coverage QC.")

    coverage_mask = mrsi_derivative(
        config.derivative_dir,
        subject,
        session,
        space="T1w",
        desc=f"{parcels.atlas_name}Coverage",
        suffix_override="mask",
    )
    if not coverage_mask.exists() or config.overwrite_transform or config.overwrite:
        apply_transforms(
            t1_reference,
            mrsi_brainmask,
            mrsi_to_t1,
            coverage_mask,
            interpolation="nearestNeighbor",
            threads=config.nthreads,
        )

    atlas_t1 = _labels(parcels.atlas_t1)
    atlas_mrsi = _labels(parcels.atlas_mrsi)
    support_t1 = load_3d_data(coverage_mask, dtype=np.float32, label="T1-space MRSI coverage mask")[1] > 0.5
    labels = read_labels(parcels.labels)
    crlb_data = {met: _optional_data(path) for met, path in crlb_maps.items()}
    qc_data = {met: _optional_data(path, boolean=True) for met, path in qcmasks.items()}
    metabolites = sorted(set(crlb_data) | set(qc_data)) or [""]

    rows = []
    for _, label_row in labels.iterrows():
        parcel_id = int(label_row["parcel_id"])
        t1_parcel = atlas_t1 == parcel_id
        mrsi_parcel = atlas_mrsi == parcel_id
        t1_total = int(t1_parcel.sum())
        t1_covered = int(np.count_nonzero(t1_parcel & support_t1))
        mrsi_total = int(mrsi_parcel.sum())
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
                    "t1_mrsi_covered_voxels": t1_covered,
                    "anatomical_coverage_fraction": t1_covered / max(t1_total, 1),
                    "anatomical_coverage_percent": 100.0 * t1_covered / max(t1_total, 1),
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

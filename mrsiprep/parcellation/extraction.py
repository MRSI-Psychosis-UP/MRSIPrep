"""Regional metabolite extraction."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from mrsiprep.io.naming import parcellation_derivative
from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.utils.images import load_3d_data
from mrsiprep.utils.tables import read_labels, write_tsv


def extract_regional_metabolites(
    config,
    subject: str,
    session: str | None,
    metabolite_maps: dict[str, Path],
    parcels: ParcellationResult,
    qcmasks: dict[str, Path],
    snr_map: Path | None,
    linewidth_map: Path | None,
    crlb_maps: dict[str, Path],
    tissue_mrsi: dict[str, Path],
) -> Path:
    out = parcellation_derivative(config.derivative_dir, subject, session, space="MRSI", atlas=parcels.atlas_name, scale=parcels.scale, desc="regional_metabolites", suffix_override="tsv")
    labels_df = read_labels(parcels.labels)
    atlas_data = load_3d_data(parcels.atlas_mrsi, dtype=np.float32, label="MRSI atlas")[1].astype(int)
    snr = _load_optional(snr_map)
    linewidth = _load_optional(linewidth_map)
    tissue = {label: _load_optional(path) for label, path in tissue_mrsi.items()}
    rows = []
    for _, label_row in labels_df.iterrows():
        parcel_id = int(label_row["parcel_id"])
        parcel_mask = atlas_data == parcel_id
        if not np.any(parcel_mask):
            continue
        for met, path in metabolite_maps.items():
            data = load_3d_data(path, dtype=np.float32, label=f"{met} map")[1]
            qmask = load_3d_data(qcmasks[met], dtype=np.float32, label=f"{met} QC mask")[1].astype(bool) if met in qcmasks else np.isfinite(data)
            valid = parcel_mask & qmask & np.isfinite(data)
            values = data[valid]
            weights = snr[valid] if snr is not None else np.ones_like(values)
            weights = np.nan_to_num(weights, nan=0.0)
            weighted_mean = np.nan
            if values.size and np.sum(weights) > 0:
                weighted_mean = float(np.average(values, weights=weights))
            rows.append(
                {
                    "subject": f"sub-{subject}",
                    "session": f"ses-{session}" if session else "",
                    "atlas": parcels.atlas_name,
                    "scale": parcels.scale or "",
                    "parcel_id": parcel_id,
                    "parcel_name": label_row.get("parcel_name", parcel_id),
                    "hemisphere": label_row.get("hemisphere", "NA"),
                    "metabolite": met,
                    "mean": float(np.nanmean(values)) if values.size else np.nan,
                    "median": float(np.nanmedian(values)) if values.size else np.nan,
                    "std": float(np.nanstd(values)) if values.size else np.nan,
                    "weighted_mean": weighted_mean,
                    "n_voxels": int(valid.sum()),
                    "coverage": float(valid.sum() / max(parcel_mask.sum(), 1)),
                    "mean_snr": _masked_mean(snr, valid),
                    "mean_linewidth": _masked_mean(linewidth, valid),
                    "mean_crlb": _masked_mean(_load_optional(crlb_maps.get(met)), valid),
                    "mean_gm_fraction": _masked_mean(tissue.get("GM"), valid),
                    "mean_wm_fraction": _masked_mean(tissue.get("WM"), valid),
                    "mean_csf_fraction": _masked_mean(tissue.get("CSF"), valid),
                }
            )
    write_tsv(rows, out)
    return out


def regional_matrix(regional_table: str | Path, value_col: str = "weighted_mean") -> pd.DataFrame:
    df = pd.read_csv(regional_table, sep="\t")
    return df.pivot_table(index="parcel_id", columns="metabolite", values=value_col, aggfunc="mean")


def _load_optional(path):
    if path is None:
        return None
    path = Path(path)
    if not path.exists():
        return None
    return load_3d_data(path, dtype=np.float32)[1]


def _masked_mean(data, mask):
    if data is None or not np.any(mask):
        return np.nan
    return float(np.nanmean(data[mask]))

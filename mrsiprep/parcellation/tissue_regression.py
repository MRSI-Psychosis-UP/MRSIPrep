"""MIDAS-style (Maudsley et al. 2006, Eq. 4-5) tissue-fraction regression.

For each parcel, solve across its MRSI voxels

    Y_n = beta_GM * W_GM_n + beta_WM * W_WM_n + bias + eps

by ordinary least squares, where ``Y_n`` is the metabolite signal at voxel
``n`` and ``W_GM_n``/``W_WM_n`` are that voxel's GM/WM tissue fractions. The
fitted ``beta_GM``/``beta_WM`` are direct estimates of the pure-GM and pure-WM
metabolite concentration in the parcel -- the paper's tissue-based
quantification. This is the MIDAS-mode-only alternative to the weighted-mean
regional extraction, which reports tissue fractions only as covariates.

Eq. 5's mixed-effects multi-subject extension is out of scope for a single
recording; this module implements the single-subject Eq. 4 model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from mrsiprep.io.naming import parcellation_derivative
from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.utils.images import load_3d_data
from mrsiprep.utils.tables import read_labels, write_tsv


@dataclass
class RegressionResult:
    beta_gm: float
    beta_wm: float
    bias: float
    se_gm: float
    se_wm: float
    r_squared: float
    condition_number: float
    n_voxels: int
    rank_deficient: bool


def fit_tissue_regression(
    values: np.ndarray,
    gm_fraction: np.ndarray,
    wm_fraction: np.ndarray,
    min_voxels: int = 10,
    min_fraction_range: float = 0.2,
    condition_number_max: float = 30.0,
) -> RegressionResult:
    """Ordinary least squares fit of Y = beta_GM*W_GM + beta_WM*W_WM + bias.

    Sets ``rank_deficient=True`` (and betas/SEs to NaN) when the region has too
    few voxels, too little GM/WM fraction variation to separate the tissue
    contributions, or an ill-conditioned design matrix. Without this guard,
    ``lstsq`` on a near-homogeneous region (e.g. deep WM, W_GM ~ 0 everywhere)
    would return numerically unstable, misleading betas.
    """
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    gm = np.asarray(gm_fraction, dtype=np.float64).reshape(-1)
    wm = np.asarray(wm_fraction, dtype=np.float64).reshape(-1)

    finite = np.isfinite(values) & np.isfinite(gm) & np.isfinite(wm)
    values, gm, wm = values[finite], gm[finite], wm[finite]
    n = values.size

    nan_result = RegressionResult(
        beta_gm=np.nan, beta_wm=np.nan, bias=np.nan, se_gm=np.nan, se_wm=np.nan,
        r_squared=np.nan, condition_number=np.nan, n_voxels=int(n), rank_deficient=True,
    )
    if n < min_voxels:
        return nan_result
    gm_range = float(gm.max() - gm.min()) if n else 0.0
    wm_range = float(wm.max() - wm.min()) if n else 0.0
    if gm_range < min_fraction_range or wm_range < min_fraction_range:
        return nan_result

    design = np.column_stack([gm, wm, np.ones(n)])
    condition_number = float(np.linalg.cond(design))
    if not np.isfinite(condition_number) or condition_number > condition_number_max:
        return RegressionResult(
            beta_gm=np.nan, beta_wm=np.nan, bias=np.nan, se_gm=np.nan, se_wm=np.nan,
            r_squared=np.nan, condition_number=condition_number, n_voxels=int(n), rank_deficient=True,
        )

    coeffs, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
    beta_gm, beta_wm, bias = (float(c) for c in coeffs)

    residuals = values - design @ coeffs
    ss_res = float(residuals @ residuals)
    ss_tot = float(((values - values.mean()) ** 2).sum())
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    dof = n - design.shape[1]
    se_gm = se_wm = np.nan
    if dof > 0:
        sigma2 = ss_res / dof
        cov = sigma2 * np.linalg.inv(design.T @ design)
        se_gm = float(np.sqrt(max(cov[0, 0], 0.0)))
        se_wm = float(np.sqrt(max(cov[1, 1], 0.0)))

    return RegressionResult(
        beta_gm=beta_gm, beta_wm=beta_wm, bias=bias, se_gm=se_gm, se_wm=se_wm,
        r_squared=r_squared, condition_number=condition_number, n_voxels=int(n), rank_deficient=False,
    )


def regional_tissue_regression(
    config,
    subject: str,
    session: str | None,
    metabolite_maps: dict[str, Path],
    parcels: ParcellationResult,
    qcmasks: dict[str, Path],
    tissue_mrsi: dict[str, Path],
) -> Path:
    """Per-parcel, per-metabolite MIDAS Eq. 4 regression; writes a TSV."""
    out = parcellation_derivative(
        config.derivative_dir, subject, session, space="MRSI",
        atlas=parcels.atlas_name, scale=parcels.scale,
        desc="tissue_regression", suffix_override="tsv",
    )
    labels_df = read_labels(parcels.labels)
    atlas_data = load_3d_data(parcels.atlas_mrsi, dtype=np.float32, label="MRSI atlas")[1].astype(int)
    gm = _load_optional(tissue_mrsi.get("GM"))
    wm = _load_optional(tissue_mrsi.get("WM"))

    rows = []
    for _, label_row in labels_df.iterrows():
        parcel_id = int(label_row["parcel_id"])
        parcel_mask = atlas_data == parcel_id
        if not np.any(parcel_mask) or gm is None or wm is None:
            continue
        for met, path in metabolite_maps.items():
            data = load_3d_data(path, dtype=np.float32, label=f"{met} map")[1]
            qmask = (
                load_3d_data(qcmasks[met], dtype=np.float32, label=f"{met} QC mask")[1].astype(bool)
                if met in qcmasks else np.isfinite(data)
            )
            valid = parcel_mask & qmask & np.isfinite(data) & np.isfinite(gm) & np.isfinite(wm)
            result = fit_tissue_regression(data[valid], gm[valid], wm[valid])
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
                    "beta_gm": result.beta_gm,
                    "beta_wm": result.beta_wm,
                    "bias": result.bias,
                    "se_gm": result.se_gm,
                    "se_wm": result.se_wm,
                    "r_squared": result.r_squared,
                    "condition_number": result.condition_number,
                    "n_voxels": result.n_voxels,
                    "rank_deficient": result.rank_deficient,
                }
            )
    write_tsv(rows, out)
    return out


def _load_optional(path):
    if path is None:
        return None
    path = Path(path)
    if not path.exists():
        return None
    return load_3d_data(path, dtype=np.float32)[1]

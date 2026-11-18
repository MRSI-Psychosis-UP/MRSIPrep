"""Voxelwise MRSI QC masks."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.mrsi.quantification_tools import get_tool, normalize_linewidth_to_hz
from mrsiprep.utils.images import load_3d_data, save_nifti
from mrsiprep.utils.tables import write_tsv

# Same key spellings as mrsiprep.mrsi.t1_correction._FIELD_KEYS (not imported
# directly: that module's leading-underscore name is private to it).
_FIELD_STRENGTH_KEYS = ("MagneticFieldStrength", "FieldStrength")


def _field_strength(mrsinmrs: dict | None) -> float | None:
    common = (mrsinmrs or {}).get("CommonMetadata") or {}
    for key in _FIELD_STRENGTH_KEYS:
        if key in common:
            return float(common[key])
    return None


def make_quality_masks(config, subject: str, session: str | None, metabolite_maps: dict[str, Path], crlb_maps: dict[str, Path], snr_map: Path | None, linewidth_map: Path | None, brainmask: Path) -> tuple[dict[str, Path], Path]:
    tool = get_tool(config.quantification_tool)
    _, brain_data = load_3d_data(brainmask, dtype=np.float32, label="MRSI brain mask")
    brain = brain_data.astype(bool)
    snr = tool.snr_scale(load_3d_data(snr_map, dtype=np.float32, label="SNR map")[1]) if snr_map and snr_map.exists() else None
    linewidth = None
    if linewidth_map and linewidth_map.exists():
        linewidth = tool.linewidth_scale(load_3d_data(linewidth_map, dtype=np.float32, label="linewidth map")[1])
        linewidth = normalize_linewidth_to_hz(linewidth, config.linewidth_unit, config.nucleus, _field_strength(config.mrsinmrs))
    qcmasks: dict[str, Path] = {}
    rows = []

    for met, path in metabolite_maps.items():
        img, data = load_3d_data(path, dtype=np.float32, label=f"{met} map")
        mask = np.isfinite(data) & brain
        crlb = tool.crlb_scale(load_3d_data(crlb_maps[met], dtype=np.float32, label=f"{met} CRLB map")[1]) if met in crlb_maps and crlb_maps[met].exists() else None
        if snr is not None:
            mask &= snr >= config.snr_min
        if linewidth is not None:
            mask &= linewidth <= config.linewidth_max
        if crlb is not None:
            mask &= crlb <= config.crlb_max
        out = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", met=met, desc="qcmask", suffix_override="mask")
        qcmasks[met] = save_nifti(mask.astype(np.uint8), img, out, dtype=np.uint8)
        valid = mask & np.isfinite(data)
        rows.append(
            {
                "metabolite": met,
                "n_total_voxels": int(brain.sum()),
                "mean_snr": _safe_mean(snr, valid),
                "median_snr": _safe_median(snr, valid),
                "mean_linewidth": _safe_mean(linewidth, valid),
                "median_linewidth": _safe_median(linewidth, valid),
                "mean_crlb": _safe_mean(crlb, valid),
                "median_crlb": _safe_median(crlb, valid),
            }
        )
    summary = mrsi_derivative(config.derivative_dir, subject, session, desc="mrsiqc", suffix_override="tsv")
    write_tsv(rows, summary)
    return qcmasks, summary


def _safe_mean(data, mask):
    if data is None or not np.any(mask):
        return np.nan
    return float(np.nanmean(data[mask]))


def _safe_median(data, mask):
    if data is None or not np.any(mask):
        return np.nan
    return float(np.nanmedian(data[mask]))

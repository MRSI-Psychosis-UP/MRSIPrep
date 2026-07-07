"""MRSI mask helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.utils.images import load_3d_data, save_nifti


def ensure_brainmask(config, subject: str, session: str | None, existing: Path | None, water_map: Path | None, metabolite_maps: dict[str, Path]) -> Path:
    if existing and existing.exists():
        return existing
    out = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", desc="brain", suffix_override="mask")
    if out.exists() and not config.overwrite:
        return out
    if water_map and water_map.exists():
        ref, data = load_3d_data(water_map, dtype=np.float32, label="water map")
        mask = data > 0
    elif metabolite_maps:
        first, first_data = load_3d_data(next(iter(metabolite_maps.values())), dtype=np.float32, label="metabolite map")
        mask = np.zeros(first.shape[:3], dtype=bool)
        mask |= np.isfinite(first_data) & (first_data > 0)
        for path in metabolite_maps.values():
            _, data = load_3d_data(path, dtype=np.float32, label="metabolite map")
            mask |= np.isfinite(data) & (data > 0)
        ref = first
    else:
        raise ValueError("Cannot create MRSI brainmask without water or metabolite maps.")
    return save_nifti(mask.astype(np.uint8), ref, out, dtype=np.uint8)

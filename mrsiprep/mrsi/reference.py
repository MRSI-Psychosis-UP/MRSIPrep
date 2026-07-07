"""MRSI reference image generation."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.utils.images import load_3d_data, save_nifti


def generate_reference(config, subject: str, session: str | None, metabolite_maps: dict[str, Path], preferred_met: str | None = None) -> Path:
    out = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", desc="reference", suffix_override="mrsi")
    if out.exists() and not config.overwrite:
        return out
    preferred = preferred_met or config.ref_met
    if preferred in metabolite_maps:
        img, data = load_3d_data(metabolite_maps[preferred], dtype=np.float32, label=f"{preferred} map")
        data = np.nan_to_num(data, nan=0.0)
    else:
        loaded = [load_3d_data(path, dtype=np.float32, label="metabolite map") for path in metabolite_maps.values()]
        if not loaded:
            raise ValueError("No metabolite maps available to build MRSI reference.")
        data = np.stack([np.nan_to_num(data, nan=0.0) for _, data in loaded], axis=0)
        valid = data != 0
        counts = valid.sum(axis=0)
        summed = data.sum(axis=0)
        data = np.divide(summed, counts, out=np.zeros_like(summed), where=counts > 0)
        img = loaded[0][0]
    return save_nifti(data.astype(np.float32), img, out, dtype=np.float32)

"""Tissue correction helpers."""

from __future__ import annotations

import numpy as np


def normalize_fractions(gm: np.ndarray, wm: np.ndarray, csf: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    total = gm + wm + csf
    return (
        np.divide(gm, total, out=np.zeros_like(gm), where=total > 0),
        np.divide(wm, total, out=np.zeros_like(wm), where=total > 0),
        np.divide(csf, total, out=np.zeros_like(csf), where=total > 0),
    )

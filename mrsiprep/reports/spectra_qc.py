"""MRSI QC report helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_qc_summary(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t")

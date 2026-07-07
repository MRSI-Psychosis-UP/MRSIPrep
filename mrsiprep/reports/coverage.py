"""Coverage report helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def summarize_coverage(regional_table: str | Path) -> pd.DataFrame:
    df = pd.read_csv(regional_table, sep="\t")
    return df.groupby(["parcel_id", "parcel_name"], dropna=False)["coverage"].mean().reset_index()

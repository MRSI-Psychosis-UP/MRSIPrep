"""Node table export."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_nodes(regional_table: str | Path | pd.DataFrame) -> pd.DataFrame:
    df = regional_table if isinstance(regional_table, pd.DataFrame) else pd.read_csv(regional_table, sep="\t")
    grouped = df.groupby(["parcel_id", "parcel_name", "hemisphere"], dropna=False).agg(
        coverage=("coverage", "mean"),
        gm_fraction=("mean_gm_fraction", "mean"),
        wm_fraction=("mean_wm_fraction", "mean"),
        csf_fraction=("mean_csf_fraction", "mean"),
    )
    nodes = grouped.reset_index()
    nodes["x"] = pd.NA
    nodes["y"] = pd.NA
    nodes["z"] = pd.NA
    return nodes[["parcel_id", "parcel_name", "hemisphere", "x", "y", "z", "coverage", "gm_fraction", "wm_fraction", "csf_fraction"]]

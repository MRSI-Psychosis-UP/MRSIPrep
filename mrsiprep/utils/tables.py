"""Table helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_tsv(rows: list[dict], out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, sep="\t", index=False)
    return out_path


def read_labels(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")
    if "index" in df.columns and "parcel_id" not in df.columns:
        df = df.rename(columns={"index": "parcel_id", "name": "parcel_name"})
    if "parcel_id" not in df.columns:
        raise ValueError(f"Label table missing parcel_id/index column: {path}")
    if "parcel_name" not in df.columns:
        df["parcel_name"] = df["parcel_id"].astype(str)
    return df

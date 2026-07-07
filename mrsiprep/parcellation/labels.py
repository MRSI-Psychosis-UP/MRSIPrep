"""Label table helpers."""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pandas as pd


def write_labels(indices, labels, out_path: str | Path) -> Path:
    rows = []
    for index, label in zip(indices, labels):
        name = label.decode() if isinstance(label, bytes) else str(label)
        rows.append(
            {
                "parcel_id": int(index),
                "parcel_name": name,
                "hemisphere": infer_hemisphere(name),
                "color": "#{:06x}".format(random.randint(0, 0xFFFFFF)),
            }
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, sep="\t", index=False)
    return out_path


def normalize_label_table(path: str | Path, out_path: str | Path | None = None) -> Path:
    path = Path(path)
    df = pd.read_csv(path, sep="\t")
    if "index" in df.columns and "parcel_id" not in df.columns:
        df = df.rename(columns={"index": "parcel_id"})
    if "name" in df.columns and "parcel_name" not in df.columns:
        df = df.rename(columns={"name": "parcel_name"})
    if "parcel_name" not in df.columns:
        df["parcel_name"] = df["parcel_id"].astype(str)
    if "hemisphere" not in df.columns:
        df["hemisphere"] = df["parcel_name"].map(infer_hemisphere)
    out_path = Path(out_path) if out_path else path
    if out_path == path and {"parcel_id", "parcel_name"}.issubset(df.columns):
        return path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, sep="\t", index=False)
    return out_path


def copy_labels(src: str | Path, dst: str | Path) -> Path:
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return normalize_label_table(dst)


def infer_hemisphere(name: str) -> str:
    lower = str(name).lower()
    if "lh" in lower or "left" in lower or "ctx-l" in lower:
        return "L"
    if "rh" in lower or "right" in lower or "ctx-r" in lower:
        return "R"
    return "NA"

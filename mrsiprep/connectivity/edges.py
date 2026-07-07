"""Edge table export."""

from __future__ import annotations

import pandas as pd


def build_edges(similarity: pd.DataFrame, method: str) -> pd.DataFrame:
    rows = []
    labels = list(similarity.index)
    for i, source in enumerate(labels):
        for target in labels[i + 1 :]:
            weight = similarity.loc[source, target]
            if pd.isna(weight):
                continue
            rows.append({"source": source, "target": target, "weight": float(weight), "method": method})
    return pd.DataFrame(rows)

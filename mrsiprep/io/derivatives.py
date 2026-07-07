"""Derivative directory helpers."""

from __future__ import annotations

import json
from pathlib import Path


def init_derivative(root: str | Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    desc = root / "dataset_description.json"
    if not desc.exists():
        desc.write_text(
            json.dumps(
                {
                    "Name": "MRSIPrep derivatives",
                    "BIDSVersion": "1.10.0",
                    "DatasetType": "derivative",
                    "GeneratedBy": [{"Name": "MRSIPrep"}],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return root

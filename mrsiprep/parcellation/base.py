"""Parcellation result objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParcellationResult:
    atlas_mrsi: Path
    labels: Path
    atlas_t1: Path | None = None
    atlas_mni: Path | None = None
    parcel_fractions: Path | None = None
    mode: str = "unknown"
    atlas_name: str = "unknown"
    scale: str | None = None

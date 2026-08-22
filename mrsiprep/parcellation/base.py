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
    # Gyral-WM growth (mm) this parcellation was built with. Only set when
    # --chimera-grow named several values, so it distinguishes them; left
    # None for the ordinary single-value case.
    grow: int | None = None

    @property
    def parcellation_id(self) -> str:
        """Stable key for this parcellation within a recording.

        Used to key the per-parcellation regional/profile/connectivity
        outputs when several parcellations are built in one run, and as the
        heading for that parcellation's report section.
        """
        parts = [self.atlas_name]
        if self.scale:
            parts.append(str(self.scale))
        if self.grow is not None:
            parts.append(f"grow{self.grow}mm")
        return "-".join(parts)

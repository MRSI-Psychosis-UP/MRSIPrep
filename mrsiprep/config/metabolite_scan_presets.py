"""Curated per-nucleus metabolite scan-candidate suggestions, loaded from
JSON (:data:`METABOLITE_SCAN_PRESETS_JSON`).

This is deliberately separate from :mod:`mrsiprep.config.nuclei`, which holds
pipeline-facing config (voxel-quality thresholds, alias spellings used to
*locate* an already-quantified metabolite map). This file instead backs the
batch-import wizard's MRSI scan step: once the user names which nucleus/
resonance they are importing, :func:`scan_candidates` lists the known
metabolite (and combined-signal) labels for that nucleus as scan-pattern
suggestions -- a convenience for populating the picker, not something any
processing step reads.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

METABOLITE_SCAN_PRESETS_JSON = Path(__file__).with_name("metabolite_scan_presets.json")


def load_metabolite_scan_presets(path: str | Path = METABOLITE_SCAN_PRESETS_JSON) -> dict[str, dict[str, Any]]:
    """Read the preset file, keyed by nucleus name."""
    json_path = Path(path)
    with json_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict) or not isinstance(raw.get("nuclei"), list):
        raise ValueError(f"{json_path} must be a JSON object with a 'nuclei' list.")

    table: dict[str, dict[str, Any]] = {}
    for entry in raw["nuclei"]:
        if not isinstance(entry, dict) or not entry.get("nucleus"):
            raise ValueError(f"{json_path} has a 'nuclei' entry with no 'nucleus' name: {entry!r}.")
        table[entry["nucleus"]] = entry
    return table


@lru_cache(maxsize=1)
def _presets() -> dict[str, dict[str, Any]]:
    return load_metabolite_scan_presets(METABOLITE_SCAN_PRESETS_JSON)


def available_preset_nuclei() -> list[str]:
    """Nuclei this preset file has scan-candidate suggestions for."""
    return sorted(_presets())


def scan_candidates(nucleus: str) -> list[str]:
    """Metabolite/combined-signal labels suggested for ``nucleus``.

    Returns an empty list for a nucleus with no curated presets, rather than
    raising -- the wizard's metabolite picker already supports free-text
    custom entries, so an unrecognized nucleus just means an empty
    suggestion list, not a blocked step.
    """
    entry = _presets().get(nucleus)
    if entry is None:
        return []
    labels = [m["label"] for m in entry.get("metabolites", []) if m.get("label")]
    labels += [c["label"] for c in entry.get("combined_signals", []) if c.get("label")]
    return sorted(dict.fromkeys(labels))

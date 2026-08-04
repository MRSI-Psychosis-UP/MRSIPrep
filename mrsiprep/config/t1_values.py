"""Load curated metabolite T1 literature values from JSON configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

T1_LITERATURE_JSON = Path(__file__).with_name("t1_literature.json")

_REQUIRED_ENTRY_KEYS = {
    "t1_s",
    "t1_sd_s",
    "t1_se_s",
    "uncertainty_type",
    "tissue",
    "resonance",
    "source",
    "doi",
    "n_subjects",
    "status",
    "notes",
}


def load_t1_literature_values(path: str | Path = T1_LITERATURE_JSON) -> dict[str, dict[float, dict[str, Any]]]:
    """Read and validate metabolite T1 literature values.

    The JSON file is intentionally data-only so users can amend/add curated
    values without editing Python source. Field-strength keys are stored as
    JSON strings (for example ``"3.0"``) and normalized to floats here to keep
    the runtime lookup API exact and unchanged.
    """
    json_path = Path(path)
    with json_path.open(encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"{json_path} must contain a JSON object keyed by metabolite name.")

    values: dict[str, dict[float, dict[str, Any]]] = {}
    for metabolite, field_entries in raw.items():
        if not isinstance(metabolite, str) or not metabolite:
            raise ValueError(f"{json_path} has an invalid metabolite key: {metabolite!r}.")
        if not isinstance(field_entries, dict):
            raise ValueError(f"{json_path} entry for {metabolite!r} must be an object keyed by field strength.")

        values[metabolite] = {}
        for field_strength, entry in field_entries.items():
            try:
                field_strength_t = float(field_strength)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{json_path} field-strength key for {metabolite!r} is not numeric: {field_strength!r}.") from exc

            if not isinstance(entry, dict):
                raise ValueError(f"{json_path} entry for {metabolite!r} at {field_strength!r}T must be an object.")
            missing = sorted(_REQUIRED_ENTRY_KEYS.difference(entry))
            if missing:
                raise ValueError(
                    f"{json_path} entry for {metabolite!r} at {field_strength!r}T is missing required keys: "
                    f"{', '.join(missing)}."
                )
            status = entry["status"]
            if status not in {"verified", "proxy", "derived", "todo"}:
                raise ValueError(f"{json_path} entry for {metabolite!r} at {field_strength!r}T has invalid status {status!r}.")
            t1_s = entry["t1_s"]
            if status != "todo" and t1_s is None:
                raise ValueError(f"{json_path} entry for {metabolite!r} at {field_strength!r}T has status {status!r} but no t1_s.")
            if t1_s is not None and float(t1_s) <= 0:
                raise ValueError(f"{json_path} entry for {metabolite!r} at {field_strength!r}T has non-positive t1_s={t1_s!r}.")

            values[metabolite][field_strength_t] = entry

    return values


@lru_cache(maxsize=1)
def _default_t1_literature_values() -> dict[str, dict[float, dict[str, Any]]]:
    return load_t1_literature_values(T1_LITERATURE_JSON)


METABOLITE_T1_VALUES = _default_t1_literature_values()

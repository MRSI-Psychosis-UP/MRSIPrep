"""General utilities."""

from __future__ import annotations

import csv
import re
from pathlib import Path


def format_elapsed_hm(seconds: float) -> str:
    """Elapsed time as hours-minutes (e.g. '2h05m'), falling back to seconds
    for sub-minute durations (e.g. cached reruns)."""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, _ = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def normalize_subject(label: str) -> str:
    label = str(label).strip()
    return label[4:] if label.startswith("sub-") else label


def normalize_session(label: str | None) -> str | None:
    if label is None:
        return None
    label = str(label).strip()
    if not label:
        return None
    if label.startswith("ses-"):
        label = label[4:]
    if label.upper().startswith("T"):
        return f"V{label[1:]}"
    return label


def parse_bids_entities(filename: str | Path) -> dict[str, str | None]:
    base = Path(filename).name
    entities: dict[str, str | None] = {}
    for key in ("sub", "ses", "run", "acq", "space", "res", "met", "desc", "label", "atlas", "scale"):
        match = re.search(rf"{key}-([^_]+)", base)
        entities[key] = match.group(1) if match else None
    return entities


def read_participant_pairs(path: str | Path) -> list[tuple[str, str | None]]:
    path = Path(path)
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    pairs: list[tuple[str, str | None]] = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        headers = reader.fieldnames or []
        sub_col = next((h for h in headers if h.lower() in {"participant_id", "subject", "subject_id", "sub", "id"}), None)
        ses_col = next((h for h in headers if h.lower() in {"session", "session_id", "ses"}), None)
        if sub_col is None:
            raise ValueError("Participants file must contain a subject column.")
        for row in reader:
            sub = str(row.get(sub_col, "")).strip()
            ses = str(row.get(ses_col, "")).strip() if ses_col else None
            if not sub:
                continue
            pairs.append((normalize_subject(sub), normalize_session(ses)))
    return list(dict.fromkeys(pairs))

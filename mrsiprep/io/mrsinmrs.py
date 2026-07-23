"""MRSinMRS (Lin et al. 2021, PMID 33559967) sequence-parameter reporting.

Reads an optional dataset-level ``mrsinmrs.json`` at the BIDS root, carrying
MRSI acquisition/hardware/reconstruction parameters so they can be surfaced
in each subject/session's QC report for reproducibility and transparency.
This file is never required for processing -- its absence just means the
report's MRSinMRS section is omitted.
"""

from __future__ import annotations

import json
from pathlib import Path

from mrsiprep.utils.misc import normalize_session, normalize_subject

MRSINMRS_FILENAME = "mrsinmrs.json"


def load_mrsinmrs(bids_dir: str | Path) -> dict | None:
    """Parse ``<bids_dir>/mrsinmrs.json`` if present.

    Returns None if the file does not exist (this is the expected default
    case). Raises ValueError on a malformed file, matching
    load_bids_filters()'s "loud on error, silent only when absent" style.
    """
    path = Path(bids_dir) / MRSINMRS_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object at the top level.")
    unsupported = set(data) - {"CommonMetadata", "Recordings"}
    if unsupported:
        raise ValueError(
            f"{path} has unsupported top-level key(s) {sorted(unsupported)}; "
            "only 'CommonMetadata' and 'Recordings' are supported."
        )
    return data


def resolve_mrsinmrs(parsed: dict | None, subject: str, session: str | None) -> dict | None:
    """Merge CommonMetadata with the matching Recordings entry.

    Recording match order: exact subject+session, then subject-only (a
    Recordings entry with no "ses" key applies to all of that subject's
    sessions). Returns None only if `parsed` itself is None or the file
    has no CommonMetadata and no matching Recordings entry.
    """
    if not parsed:
        return None
    common = dict(parsed.get("CommonMetadata") or {})
    recordings = parsed.get("Recordings") or []
    sub_norm = normalize_subject(subject)
    ses_norm = normalize_session(session)

    match = None
    for entry in recordings:
        entry_sub = normalize_subject(entry.get("sub", ""))
        if entry_sub != sub_norm:
            continue
        entry_ses = normalize_session(entry.get("ses"))
        if entry_ses == ses_norm:
            match = entry
            break
        if entry_ses is None and match is None:
            match = entry
    merged = {**common, **{k: v for k, v in (match or {}).items() if k not in {"sub", "ses"}}}
    return merged or None

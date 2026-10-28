"""MRSinMRS (Lin et al. 2021, PMID 33559967) sequence-parameter reporting.

Reads ``derivatives/mrsi-orig/mrsinmrs.json`` or an explicitly selected file, carrying
MRSI acquisition/hardware/reconstruction parameters so they can be surfaced
in each subject/session's QC report for reproducibility and transparency.
Acquisition metadata is required for processing. Fields are otherwise free-form (no
enforced schema), *except* the small whitelist of TR/flip-angle/field-
strength key spellings that :mod:`mrsiprep.mrsi.t1_correction` reads for
``--t1-correction literature`` -- see that module's ``_TR_KEYS``/
``_FLIP_KEYS``/``_FIELD_KEYS`` and docs/future_development.md's
"Recognized mrsinmrs.json keys" table for the canonical spelling of each.
"""

from __future__ import annotations

import json
from pathlib import Path

from mrsiprep.utils.misc import normalize_session, normalize_subject

MRSINMRS_FILENAME = "mrsinmrs.json"


def load_mrsinmrs(
    bids_dir: str | Path,
    metadata_file: str | Path | None = None,
    *,
    required: bool = True,
) -> dict | None:
    """Read the selected file, defaulting to the MRSI input root.

    An explicit path overrides the default; there is no BIDS-root fallback.
    ``required=False`` supports constructing library configuration objects
    before inputs exist. CLI and full workflow entry points require metadata.
    """
    path = Path(metadata_file) if metadata_file is not None else Path(bids_dir) / "derivatives" / "mrsi-orig" / MRSINMRS_FILENAME
    if not path.is_file():
        if not required:
            return None
        raise FileNotFoundError(
            f"Required MRSinMRS acquisition metadata file not found: {path}. "
            "Place mrsinmrs.json in <bids_dir>/derivatives/mrsi-orig/ "
            "or provide --mrsinmrs-file /path/to/mrsinmrs.json."
        )
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
    common = data.get("CommonMetadata", {})
    recordings = data.get("Recordings", [])
    if not isinstance(common, dict):
        raise ValueError(f"{path}: CommonMetadata must be a JSON object.")
    if not isinstance(recordings, list) or any(not isinstance(entry, dict) for entry in recordings):
        raise ValueError(f"{path}: Recordings must be a list of JSON objects.")
    if not common and not any(set(entry) - {"sub", "ses"} for entry in recordings):
        raise ValueError(f"{path} contains no acquisition metadata. Populate CommonMetadata or Recordings.")
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

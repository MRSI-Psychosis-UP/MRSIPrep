"""Per-position Chimera scheme letters, loaded from JSON.

A ``--chimera-scheme`` code (e.g. ``"LFMIHIFIFF"``) is a 10-character string,
one letter per supra-region, in a fixed order (see :data:`SUPRA_REGIONS`).
Which letters are valid, and what atlas each one names, is defined by the
upstream ``chimera-brainparcellation`` package's own
``config/supraregions_dictionary.json`` -- not reproducible from anything
else in this repo (mrsiprep only shells out to the installed ``chimera`` CLI,
see :mod:`mrsiprep.interfaces.chimera`), so this is a trimmed, versioned copy
of that mapping (name/citation/default flag, plus cortical-only scale/seg
variants), captured from chimera-brainparcellation 0.4.1. Re-sync
:data:`CHIMERA_SCHEMES_JSON` by hand if the installed chimera's own
supraregions_dictionary.json adds/removes letters.

This mirrors :mod:`mrsiprep.config.nuclei`/``nuclei.json``: adding/updating a
letter is a data change, not a code change.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CHIMERA_SCHEMES_JSON = Path(__file__).with_name("chimera_schemes.json")

#: Supra-region order a --chimera-scheme code's letters map to, position by
#: position. Matches upstream chimera's own JSON key order (and therefore the
#: order its `chimera` CLI expects), not alphabetical or any other ordering.
SUPRA_REGIONS: tuple[str, ...] = (
    "Cortical",
    "Subcortical",
    "Thalamus",
    "Amygdala",
    "Hippocampus",
    "Hypothalamus",
    "Cerebellum",
    "Brainstem",
    "GyralWM",
    "WhiteMatter",
)

#: Human-readable label for each position, for UI/error messages.
SUPRA_REGION_LABELS: dict[str, str] = {
    "Cortical": "Cortex",
    "Subcortical": "Basal ganglia",
    "Thalamus": "Thalamus",
    "Amygdala": "Amygdala",
    "Hippocampus": "Hippocampus",
    "Hypothalamus": "Hypothalamus",
    "Cerebellum": "Cerebellum",
    "Brainstem": "Brainstem",
    "GyralWM": "Gyral WM",
    "WhiteMatter": "White matter",
}

#: Letter used to skip a supra-region entirely, matching upstream chimera's
#: own code-string convention (not currently surfaced in mrsiprep's own
#: --chimera-scheme validation prior to this, since content wasn't checked at
#: all -- see mrsiprep.config.settings._validate_parcellation_lists).
NONE_KEY = "N"


class ChimeraSchemeError(ValueError):
    """Raised for a malformed or unsupported --chimera-scheme code."""


def load_chimera_schemes(path: str | Path = CHIMERA_SCHEMES_JSON) -> dict[str, dict[str, dict[str, Any]]]:
    """Read and validate the per-position letter table.

    Validation is deliberately strict and eager, matching
    :func:`mrsiprep.config.nuclei.load_nuclei`'s stance: a malformed
    contribution fails at import, not mid-run.
    """
    json_path = Path(path)
    with json_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"{json_path} must contain a non-empty JSON object keyed by supra-region.")
    missing_regions = [region for region in SUPRA_REGIONS if region not in raw]
    if missing_regions:
        raise ValueError(f"{json_path} is missing supra-region(s): {', '.join(missing_regions)}.")

    for region, letters in raw.items():
        if not isinstance(letters, dict) or not letters:
            raise ValueError(f"{json_path} entry for {region!r} must be a non-empty object keyed by letter.")
        defaults = [letter for letter, info in letters.items() if info.get("default")]
        if len(defaults) != 1:
            raise ValueError(
                f"{json_path} entry for {region!r} must mark exactly one letter as the default, "
                f"found: {defaults or 'none'}."
            )
        for letter, info in letters.items():
            if not isinstance(letter, str) or len(letter) != 1 or not letter.isalpha():
                raise ValueError(f"{json_path} entry for {region!r} has a non-single-letter key: {letter!r}.")
            if letter == NONE_KEY:
                raise ValueError(
                    f"{json_path} entry for {region!r} uses reserved skip-letter {NONE_KEY!r} as an atlas key."
                )
            if "name" not in info:
                raise ValueError(f"{json_path} entry for {region!r}/{letter!r} is missing 'name'.")
            if not str(info.get("citation", "")).strip():
                raise ValueError(
                    f"{json_path} entry for {region!r}/{letter!r} ({info['name']!r}) is missing a "
                    "non-empty 'citation'. Every atlas combinable by --chimera-scheme must carry its "
                    "own citation here, so the HTML report (mrsiprep.reports.html._chimera_citations_html) "
                    "always credits whatever a run actually selected -- fill in the atlas's own "
                    "citation before adding/enabling this letter."
                )
            if not str(info.get("full_citation", "")).strip():
                raise ValueError(
                    f"{json_path} entry for {region!r}/{letter!r} ({info['name']!r}) is missing a "
                    "non-empty 'full_citation' (authors, year, title, journal/publisher, and a DOI "
                    "when one exists -- not just the short 'citation' author/year tag). Verify it "
                    "against the real published paper before filling it in; do not guess."
                )

    return raw


@lru_cache(maxsize=1)
def _schemes() -> dict[str, dict[str, dict[str, Any]]]:
    return load_chimera_schemes(CHIMERA_SCHEMES_JSON)


def valid_letters(region: str) -> dict[str, dict[str, Any]]:
    """Letter -> info mapping for one supra-region (does not include the skip letter)."""
    return dict(_schemes()[region])


def default_letter(region: str) -> str:
    """The single default letter for one supra-region."""
    for letter, info in _schemes()[region].items():
        if info.get("default"):
            return letter
    raise ChimeraSchemeError(f"No default letter configured for supra-region {region!r}.")  # pragma: no cover


def default_code() -> str:
    """The all-default scheme code, one default letter per position in order."""
    return "".join(default_letter(region) for region in SUPRA_REGIONS)


def parse_scheme_code(code: str) -> dict[str, str]:
    """Split a --chimera-scheme code into ``{region: letter}``, validating length and letters.

    :raises ChimeraSchemeError: If the code's length doesn't match
        :data:`SUPRA_REGIONS`, or any letter isn't valid (or ``N``) for its position.
    """
    code = code.strip().upper()
    if len(code) != len(SUPRA_REGIONS):
        raise ChimeraSchemeError(
            f"--chimera-scheme {code!r} has {len(code)} letters, expected {len(SUPRA_REGIONS)} "
            f"(one per supra-region: {', '.join(SUPRA_REGIONS)})."
        )
    by_region: dict[str, str] = {}
    for region, letter in zip(SUPRA_REGIONS, code):
        valid = set(_schemes()[region]) | {NONE_KEY}
        if letter not in valid:
            raise ChimeraSchemeError(
                f"--chimera-scheme {code!r}: {letter!r} is not valid for supra-region {region!r} "
                f"(valid: {', '.join(sorted(valid))})."
            )
        by_region[region] = letter
    return by_region


def build_scheme_code(by_region: dict[str, str]) -> str:
    """Inverse of :func:`parse_scheme_code`: compose a code string from ``{region: letter}``."""
    return "".join(by_region[region] for region in SUPRA_REGIONS)

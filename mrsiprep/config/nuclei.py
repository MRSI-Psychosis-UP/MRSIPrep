"""Per-nucleus configuration, loaded from JSON.

MRSIPrep's processing stages -- registration, partial-volume correction,
parcellation, resampling -- operate on quantified metabolite maps and are
indifferent to which nucleus produced them. What *is* nucleus-dependent is the
surrounding metadata: sensible voxel-quality thresholds, and the alias
spellings used to locate a metabolite's input map.

Both live in :data:`NUCLEI_JSON` rather than in Python, so adding support for a
new nucleus is a data change a contributor can make without touching pipeline
code (see docs/extending.md). This mirrors
:mod:`mrsiprep.config.t1_values`/``t1_literature.json``.

Thresholds for non-proton nuclei ship deliberately uncurated
(``"quality_defaults": null``): 31P and 2H SNR/CRLB regimes differ
substantially from 1H, and shipping guessed numbers would look authoritative
while being wrong. Resolving them raises with a message naming this file --
the same "refuse to guess" stance as
:func:`mrsiprep.mrsi.t1_correction.resolve_metabolite_t1`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

NUCLEI_JSON = Path(__file__).with_name("nuclei.json")

DEFAULT_NUCLEUS = "1H"

_REQUIRED_ENTRY_KEYS = {
    "display_name",
    "aliases",
    "quality_defaults",
    "metabolite_aliases",
    "status",
    "notes",
    "source",
}
_REQUIRED_QUALITY_KEYS = {"snr_min", "linewidth_max", "crlb_max"}
_VALID_STATUSES = {"curated", "uncurated"}


class NucleusError(ValueError):
    """Raised for an unknown nucleus, or one whose values aren't curated."""


def load_nuclei(path: str | Path = NUCLEI_JSON) -> dict[str, dict[str, Any]]:
    """Read and validate the nucleus table.

    Validation is deliberately strict and eager, so a malformed contribution
    fails at import with a message naming the offending entry rather than
    surfacing as a confusing error mid-run.
    """
    json_path = Path(path)
    with json_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"{json_path} must contain a non-empty JSON object keyed by nucleus name.")

    for name, entry in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"{json_path} has an invalid nucleus key: {name!r}.")
        if not isinstance(entry, dict):
            raise ValueError(f"{json_path} entry for {name!r} must be an object.")
        missing = sorted(_REQUIRED_ENTRY_KEYS.difference(entry))
        if missing:
            raise ValueError(f"{json_path} entry for {name!r} is missing required keys: {', '.join(missing)}.")
        if entry["status"] not in _VALID_STATUSES:
            raise ValueError(
                f"{json_path} entry for {name!r} has invalid status {entry['status']!r} "
                f"(expected one of: {', '.join(sorted(_VALID_STATUSES))})."
            )
        if not isinstance(entry["aliases"], list) or not entry["aliases"]:
            raise ValueError(f"{json_path} entry for {name!r} must list at least one alias.")
        if not isinstance(entry["metabolite_aliases"], dict):
            raise ValueError(f"{json_path} entry for {name!r} has a non-object metabolite_aliases.")

        quality = entry["quality_defaults"]
        if quality is None:
            if entry["status"] != "uncurated":
                raise ValueError(
                    f"{json_path} entry for {name!r} has no quality_defaults but status "
                    f"{entry['status']!r}; use status 'uncurated' when values are absent."
                )
        else:
            if not isinstance(quality, dict):
                raise ValueError(f"{json_path} entry for {name!r} has a non-object quality_defaults.")
            missing_quality = sorted(_REQUIRED_QUALITY_KEYS.difference(quality))
            if missing_quality:
                raise ValueError(
                    f"{json_path} entry for {name!r} quality_defaults is missing: {', '.join(missing_quality)}."
                )

    _check_aliases_unambiguous(raw, json_path)
    return raw


def _check_aliases_unambiguous(table: dict[str, dict[str, Any]], json_path: Path) -> None:
    """No alias may resolve to two different nuclei.

    Checked at load time because the failure mode otherwise is silent: whichever
    entry happened to be iterated last would quietly win.
    """
    seen: dict[str, str] = {}
    for name, entry in table.items():
        for alias in [name, *entry["aliases"]]:
            key = str(alias).strip().lower()
            if key in seen and seen[key] != name:
                raise ValueError(f"{json_path} alias {alias!r} maps to both {seen[key]!r} and {name!r}.")
            seen[key] = name


@lru_cache(maxsize=1)
def _nuclei() -> dict[str, dict[str, Any]]:
    return load_nuclei(NUCLEI_JSON)


def available_nuclei() -> list[str]:
    """Canonical nucleus names, for CLI choices and error messages."""
    return sorted(_nuclei())


def canonical_nucleus(name: str) -> str:
    """Resolve any accepted spelling to its canonical name (e.g. ``proton`` -> ``1H``).

    :raises NucleusError: If the name matches no known nucleus.
    """
    key = str(name).strip().lower()
    for canonical, entry in _nuclei().items():
        if key == canonical.lower() or key in {str(a).strip().lower() for a in entry["aliases"]}:
            return canonical
    raise NucleusError(
        f"Unknown nucleus {name!r}. Known nuclei: {', '.join(available_nuclei())}. "
        f"To add another, extend {NUCLEI_JSON.name} -- see docs/extending.md."
    )


def nucleus_entry(name: str) -> dict[str, Any]:
    """Full table entry for a nucleus, resolving aliases first."""
    return _nuclei()[canonical_nucleus(name)]


def quality_defaults(name: str) -> dict[str, float]:
    """Voxel-quality thresholds for a nucleus.

    :raises NucleusError: If this nucleus ships no curated thresholds. The
        caller is expected to surface this as "pass the flags explicitly",
        which is preferable to silently applying proton values to a nucleus
        whose SNR regime is nothing like proton's.
    """
    canonical = canonical_nucleus(name)
    defaults = _nuclei()[canonical]["quality_defaults"]
    if defaults is None:
        raise NucleusError(
            f"No curated voxel-quality thresholds for {canonical}. Pass --snr-min, "
            f"--linewidth-max and --crlb-max explicitly, or contribute "
            f"citation-backed defaults to {NUCLEI_JSON.name} (see docs/extending.md). "
            "They are left uncurated on purpose: proton thresholds would not be "
            "appropriate here and guessing would look authoritative while being wrong."
        )
    return dict(defaults)


def metabolite_aliases(name: str) -> dict[str, list[str]]:
    """Alias spellings used to locate a metabolite's input map, for a nucleus."""
    return dict(nucleus_entry(name)["metabolite_aliases"])

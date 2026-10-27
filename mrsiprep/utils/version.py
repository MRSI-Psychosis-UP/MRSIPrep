"""Resolve the installed mrsiprep version in one place."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def mrsiprep_version() -> str:
    """Installed mrsiprep version, or "unknown" rather than raising -- callers
    (banner, reports, provenance) must still work even if package metadata is
    unavailable, e.g. an editable/non-installed checkout."""
    try:
        return version("mrsiprep")
    except PackageNotFoundError:
        return "unknown"

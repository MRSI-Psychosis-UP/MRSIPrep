"""The MRSIPrep on Docker wrapper."""

from __future__ import annotations

try:
    from ._version import __version__
except ImportError:
    try:
        from importlib.metadata import version

        __version__ = version("mrsiprep-docker")
    except Exception:
        __version__ = "0+unknown"

__all__ = ["__version__"]

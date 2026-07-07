"""The MRSIPrep on Docker wrapper."""

from __future__ import annotations

try:
    from ._version import __version__
except ImportError:
    __version__ = "0+unknown"

__all__ = ["__version__"]

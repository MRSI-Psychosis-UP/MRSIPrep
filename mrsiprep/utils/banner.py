"""Startup banner for the MRSIPrep CLI."""

from __future__ import annotations

from mrsiprep.utils.version import mrsiprep_version

BANNER = r"""
 ███╗   ███╗██████╗ ███████╗██╗██████╗ ██████╗ ███████╗██████╗
 ████╗ ████║██╔══██╗██╔════╝██║██╔══██╗██╔══██╗██╔════╝██╔══██╗
 ██╔████╔██║██████╔╝███████╗██║██████╔╝██████╔╝█████╗  ██████╔╝
 ██║╚██╔╝██║██╔══██╗╚════██║██║██╔═══╝ ██╔══██╗██╔══╝  ██╔═══╝
 ██║ ╚═╝ ██║██║  ██║███████║██║██║     ██║  ██║███████╗██║
 ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚═╝╚═╝     ╚═╝  ╚═╝╚══════╝╚═╝

       MRSI Post-Metabolite Quantification Pre-Processing Pipeline
"""


def print_banner() -> None:
    print(BANNER)
    print(f"       mrsiprep version: {mrsiprep_version()}\n")

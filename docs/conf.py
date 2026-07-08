"""Sphinx configuration for MRSIPrep documentation."""

import sys
from pathlib import Path

# mrsiprep.cli.parser (and its transitive imports: config.settings,
# config.defaults, io.bids) is dependency-light by design -- no numpy/nipype/
# nibabel required at import time -- specifically so sphinx-argparse can
# introspect the live parser here without needing the full scientific stack
# installed in the docs build environment.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

project = "MRSIPrep"
copyright = "2026, Federico Lucchetti"
author = "Federico Lucchetti"

extensions = [
    "myst_parser",
    "sphinxarg.ext",
]

# sphinxarg.ext's ArgParseDomain doesn't implement merge_domaindata, which
# Sphinx requires for parallel reads -- Read the Docs always builds with
# `-j auto`, so without this patch the build crashes with
# "NotImplementedError: merge_domaindata must be implemented in
# <class 'sphinxarg.ext.ArgParseDomain'>" (reproduced locally with
# `sphinx-build -j auto`; a plain serial build never hits it, which is why
# this only surfaced on Read the Docs). initial_data is just a list +
# a dict keyed by group name, so merging is a straightforward union.
def _patch_argparse_domain_for_parallel_builds() -> None:
    from sphinxarg.ext import ArgParseDomain

    def merge_domaindata(self, docnames, otherdata):
        self.data.setdefault("commands", [])
        self.data["commands"].extend(otherdata.get("commands", []))
        self.data.setdefault("commands-by-group", {})
        for group, items in otherdata.get("commands-by-group", {}).items():
            self.data["commands-by-group"].setdefault(group, []).extend(items)

    ArgParseDomain.merge_domaindata = merge_domaindata


_patch_argparse_domain_for_parallel_builds()

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

myst_enable_extensions = [
    "colon_fence",
]

# Keep straight quotes verbatim (e.g. literal JSON examples inside CLI help
# text rendered by sphinx-argparse); this is technical/code-heavy
# documentation where curly-quote typography does more harm than good.
smartquotes = False

master_doc = "index"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 3,
}

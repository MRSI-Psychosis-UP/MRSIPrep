"""Sphinx configuration for MRSIPrep documentation."""

import sys
import tomllib
from pathlib import Path

# mrsiprep.cli.parser (and its transitive imports: config.settings,
# config.defaults, io.bids) is dependency-light by design -- no numpy/nipype/
# nibabel required at import time -- specifically so sphinx-argparse can
# introspect the live parser here without needing the full scientific stack
# installed in the docs build environment. The API reference pages (below)
# do need the full stack, listed in docs/requirements.txt -- antspyx is
# never imported at module level anywhere in mrsiprep (only lazily inside
# interfaces/ants.py), so it's deliberately excluded from that list.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

project = "MRSIPrep"
copyright = "2026, Federico Lucchetti"
author = "Federico Lucchetti"
# Use the source version even when the package is not installed in the docs
# environment, or an older installed distribution is present.
release = tomllib.loads(
    (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
)["project"]["version"]
version = release

extensions = [
    "myst_parser",
    "sphinxarg.ext",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.mathjax",
]

autosummary_generate = True
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": False,
}
autodoc_typehints = "description"
autodoc_mock_imports = ["antspyx"]

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
    "dollarmath",
    "substitution",
]
myst_substitutions = {"release": release}
# Make section links such as inputs.md#maps-units-and-geometry resolvable
# across Markdown documents, including under strict warning checks.
myst_heading_anchors = 4

# Keep straight quotes verbatim (e.g. literal JSON examples inside CLI help
# text rendered by sphinx-argparse); this is technical/code-heavy
# documentation where curly-quote typography does more harm than good.
smartquotes = False

master_doc = "index"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "benchmark_smoothing.md"]

html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "collapse_navigation": True,
    "navigation_depth": 2,
    "titles_only": True,
}

# Read the Docs injects a rel="canonical" link on every built page pointing
# at this base URL + the page's path, so search engines consolidate ranking
# onto the "stable" version instead of indexing "latest" (or old tagged
# versions) as separate competing pages.
html_baseurl = "https://mrsiprep.readthedocs.io/en/stable/"

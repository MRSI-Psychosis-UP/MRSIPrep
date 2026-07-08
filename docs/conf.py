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

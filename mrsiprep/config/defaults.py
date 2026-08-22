"""Default values for MRSIPrep.

The metabolite-alias and voxel-quality tables that used to live here are now
per-nucleus data in ``config/nuclei.json`` (see :mod:`mrsiprep.config.nuclei`),
so supporting a new nucleus is a data change rather than a code change.

The two module-level names below are kept as the proton values for backwards
compatibility with anything importing them directly. Prefer the
nucleus-resolved accessors on the config -- ``config.nucleus_metabolite_aliases()``
and the already-resolved ``config.snr_min``/``linewidth_max``/``crlb_max`` --
which honour whichever nucleus the run actually declared.
"""

from .nuclei import DEFAULT_NUCLEUS, metabolite_aliases, quality_defaults

METABOLITE_ALIASES = metabolite_aliases(DEFAULT_NUCLEUS)

QUALITY_DEFAULTS = quality_defaults(DEFAULT_NUCLEUS)

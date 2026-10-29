"""Upstream quantification-tool conventions for CRLB/SNR/linewidth maps.

MRSIPrep's quality thresholds (``--crlb-max``, ``--snr-min``,
``--linewidth-max``) assume the LCModel convention: CRLB as a percentage of
the fitted amplitude, SNR as peak height over residual noise SD, and
linewidth in Hz. Declaring the upstream quantification tool lets MRSIPrep
rescale a tool's native output onto that convention before thresholding.

Only tools whose scale was verified against a primary source (the tool's
own manual or source code) are supported with automatic rescaling; see
docs/inputs.md's "Quantification tool conventions" table. A tool with an
unverified or genuinely different convention (e.g. TARQUIN's SNR
definition, or jMRUI's SNR) is deliberately NOT included here rather than
shipping a guessed conversion factor -- same "refuse to guess" stance as
:mod:`mrsiprep.config.nuclei`. ``"custom"`` performs no rescaling at all;
the user is solely responsible for pre-converting their maps to the
LCModel convention before running MRSIPrep.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


def _identity(values: np.ndarray) -> np.ndarray:
    return values


@dataclass(frozen=True)
class QuantificationToolSpec:
    name: str
    display_name: str
    crlb_scale: Callable[[np.ndarray], np.ndarray]
    snr_scale: Callable[[np.ndarray], np.ndarray]
    linewidth_scale: Callable[[np.ndarray], np.ndarray]
    notes: str


# All three verified tools already report CRLB as %, SNR as peak-height /
# residual-noise-SD, and linewidth in Hz -- the same convention MRSIPrep's
# thresholds assume -- so every scale function here is presently the
# identity. They are kept as separate, named entries (rather than one
# shared "verified" tool) so a future tool needing a real conversion only
# adds one new entry, and so each is independently traceable to the source
# that verified it.
_TOOLS: dict[str, QuantificationToolSpec] = {
    "lcmodel": QuantificationToolSpec(
        name="lcmodel",
        display_name="LCModel",
        crlb_scale=_identity,
        snr_scale=_identity,
        linewidth_scale=_identity,
        notes="Reference convention: CRLB as %SD, SNR via peak height over residual-noise SD, linewidth in Hz.",
    ),
    "fsl-mrs": QuantificationToolSpec(
        name="fsl-mrs",
        display_name="FSL-MRS",
        crlb_scale=_identity,
        snr_scale=_identity,
        linewidth_scale=_identity,
        notes="CRLB%, SNR, and FWHM(Hz) are explicitly implemented to match LCModel's convention (fsl_mrs.utils.results/qc).",
    ),
    "osprey": QuantificationToolSpec(
        name="osprey",
        display_name="Osprey",
        crlb_scale=_identity,
        snr_scale=_identity,
        linewidth_scale=_identity,
        notes=(
            "Verified only for Osprey's LCModel-wrapper path, which passes LCModel's .table values through "
            "unchanged. Osprey's own native fitting engine was not verified against a primary source -- if you "
            "used that engine rather than the LCModel wrapper, use --quantification-tool custom instead."
        ),
    ),
    "custom": QuantificationToolSpec(
        name="custom",
        display_name="Custom / other",
        crlb_scale=_identity,
        snr_scale=_identity,
        linewidth_scale=_identity,
        notes="No rescaling is performed. You are solely responsible for ensuring your maps already match MRSIPrep's expected convention.",
    ),
}

SUPPORTED_TOOLS = tuple(_TOOLS)


class QuantificationToolError(ValueError):
    """Raised for an unresolved or unsupported quantification tool."""


def get_tool(name: str) -> QuantificationToolSpec:
    try:
        return _TOOLS[name]
    except KeyError:
        raise QuantificationToolError(
            f"Unsupported --quantification-tool '{name}'. Supported values: {', '.join(SUPPORTED_TOOLS)}. "
            "Use 'custom' if your tool isn't listed; MRSIPrep will not guess its scaling."
        ) from None


def resolve_quantification_tool(cli_value: str | None, mrsinmrs: dict | None) -> str:
    """Resolve the declared quantification tool: CLI flag, then mrsinmrs.json.

    Precedence matches --mrsinmrs-file/--nucleus: an explicit CLI value
    wins; otherwise ``CommonMetadata.QuantificationTool`` is read from the
    acquisition metadata. Raises if neither is present -- this is a
    mandatory declaration, not a silently-defaulted one, because guessing
    it wrong would silently change which voxels pass QC thresholds.
    """
    if cli_value is not None:
        get_tool(cli_value)
        return cli_value
    declared = ((mrsinmrs or {}).get("CommonMetadata") or {}).get("QuantificationTool")
    if declared is None:
        raise QuantificationToolError(
            "No upstream quantification tool specified. Add \"QuantificationTool\" "
            f"(one of {', '.join(SUPPORTED_TOOLS)}) to CommonMetadata in mrsinmrs.json, "
            "or pass --quantification-tool explicitly. This is required because MRSIPrep's "
            "CRLB/SNR/linewidth thresholds assume a specific convention, and applying them "
            "to a tool with a different convention without rescaling would silently misjudge "
            "voxel quality."
        )
    get_tool(declared)
    return declared

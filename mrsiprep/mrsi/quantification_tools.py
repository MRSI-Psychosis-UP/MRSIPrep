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

Separately from the tool's CRLB/SNR/linewidth *convention*, the acquisition
metadata also declares the *unit* a tool's linewidth and CRLB maps are
actually stored in (``LinewidthUnit``, ``CRLBUnit`` in ``CommonMetadata``),
since different exports commonly differ here even among tools that agree on
everything else -- most notably linewidth, which some pipelines report in
Hz and others in ppm. Both are mandatory declarations, same rationale as
``QuantificationTool``: silently assuming the wrong one would misjudge voxel
quality rather than fail loudly. :func:`resolve_linewidth_unit` and
:func:`normalize_linewidth_to_hz` handle that declaration and conversion;
``SNRUnit`` is optional and merely recorded (SNR has no alternate unit
MRSIPrep converts between -- it is treated as unitless either way).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

# MHz per tesla, used only to convert a declared LinewidthUnit of "ppm" to
# Hz (Hz = ppm * gyromagnetic_mhz_per_t * MagneticFieldStrength). Limited to
# nuclei with curated voxel-quality thresholds (see mrsiprep/config/nuclei.py)
# -- there is no curated linewidth_max to apply a ppm-converted value against
# for an uncurated nucleus, so no conversion constant is needed for those yet.
_GYROMAGNETIC_MHZ_PER_T = {"1H": 42.577478}

SUPPORTED_LINEWIDTH_UNITS = ("Hz", "ppm")
SUPPORTED_CRLB_UNITS = ("percent",)


def _identity(values: np.ndarray) -> np.ndarray:
    return values


def resolve_linewidth_unit(cli_value: str | None, mrsinmrs: dict | None) -> str:
    """Resolve the declared linewidth unit: CLI flag, then mrsinmrs.json.

    Mandatory, same rationale as :func:`resolve_quantification_tool`:
    MRSIPrep's ``--linewidth-max`` threshold is defined in Hz, and silently
    assuming a tool's native unit would misjudge voxel quality if it is
    actually ppm (or vice versa) instead.
    """
    if cli_value is not None:
        if cli_value not in SUPPORTED_LINEWIDTH_UNITS:
            raise QuantificationToolError(f"Unsupported --linewidth-unit '{cli_value}'. Supported values: {', '.join(SUPPORTED_LINEWIDTH_UNITS)}.")
        return cli_value
    declared = ((mrsinmrs or {}).get("CommonMetadata") or {}).get("LinewidthUnit")
    if declared is None:
        raise QuantificationToolError(
            "No linewidth unit specified. Add \"LinewidthUnit\" "
            f"(one of {', '.join(SUPPORTED_LINEWIDTH_UNITS)}) to CommonMetadata in mrsinmrs.json, "
            "or pass --linewidth-unit explicitly. This is required because --linewidth-max is "
            "defined in Hz, and thresholding a ppm-reported map against it unconverted (or vice "
            "versa) would silently misjudge voxel quality."
        )
    if declared not in SUPPORTED_LINEWIDTH_UNITS:
        raise QuantificationToolError(f"Unsupported LinewidthUnit '{declared}' in mrsinmrs.json. Supported values: {', '.join(SUPPORTED_LINEWIDTH_UNITS)}.")
    return declared


def resolve_crlb_unit(cli_value: str | None, mrsinmrs: dict | None) -> str:
    """Resolve the declared CRLB unit: CLI flag, then mrsinmrs.json.

    Mandatory for the same reason as :func:`resolve_linewidth_unit`. Only
    "percent" is currently supported -- ``--crlb-max`` is defined as a
    percentage of the fitted amplitude -- but the declaration is still
    required rather than assumed, so an export in absolute units fails
    loudly instead of being thresholded as if it were already a percentage.
    """
    if cli_value is not None:
        if cli_value not in SUPPORTED_CRLB_UNITS:
            raise QuantificationToolError(f"Unsupported --crlb-unit '{cli_value}'. Supported values: {', '.join(SUPPORTED_CRLB_UNITS)}.")
        return cli_value
    declared = ((mrsinmrs or {}).get("CommonMetadata") or {}).get("CRLBUnit")
    if declared is None:
        raise QuantificationToolError(
            "No CRLB unit specified. Add \"CRLBUnit\" "
            f"(currently only {', '.join(SUPPORTED_CRLB_UNITS)} is supported) to CommonMetadata in "
            "mrsinmrs.json, or pass --crlb-unit explicitly. This is required because --crlb-max is "
            "defined as a percentage, and thresholding an absolute-unit map against it unconverted "
            "would silently misjudge voxel quality."
        )
    if declared not in SUPPORTED_CRLB_UNITS:
        raise QuantificationToolError(f"Unsupported CRLBUnit '{declared}' in mrsinmrs.json. Supported values: {', '.join(SUPPORTED_CRLB_UNITS)}.")
    return declared


def normalize_linewidth_to_hz(values: np.ndarray, unit: str, nucleus: str, field_strength_t: float | None) -> np.ndarray:
    """Convert a loaded linewidth map to Hz, MRSIPrep's internal convention.

    :param unit: As resolved by :func:`resolve_linewidth_unit` ("Hz" or "ppm").
    :param field_strength_t: ``MagneticFieldStrength`` from mrsinmrs.json;
        required (and only meaningful) when ``unit == "ppm"``.
    :raises QuantificationToolError: If ``unit == "ppm"`` and either the
        field strength is missing, or this nucleus has no known Larmor
        frequency to convert with -- refusing to guess, same stance as
        :mod:`mrsiprep.config.nuclei`.
    """
    if unit == "Hz":
        return values
    if field_strength_t is None:
        raise QuantificationToolError("LinewidthUnit is \"ppm\" but no MagneticFieldStrength is declared in mrsinmrs.json; it is required to convert ppm to Hz.")
    mhz_per_t = _GYROMAGNETIC_MHZ_PER_T.get(nucleus)
    if mhz_per_t is None:
        raise QuantificationToolError(f"LinewidthUnit \"ppm\" cannot be converted to Hz for nucleus {nucleus!r}: no gyromagnetic ratio is curated for it. Report linewidth in Hz instead, or contribute a curated value.")
    return values * mhz_per_t * field_strength_t


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

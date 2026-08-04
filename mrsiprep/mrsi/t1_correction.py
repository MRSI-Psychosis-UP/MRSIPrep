"""Protocol-level T1 saturation correction for quantified MRSI metabolite maps.

Raw fitted metabolite amplitudes are systematically underestimated when the
acquisition's TR is short relative to a metabolite's own T1, since the spin
system has not fully relaxed between excitations. This module applies a
single scalar correction factor per metabolite per recording, derived from
the standard spoiled-FID/Ernst-angle steady-state signal equation:

    S/S0 = sin(alpha) * (1 - exp(-TR/T1)) / (1 - cos(alpha) * exp(-TR/T1))

using TR/flip angle read from the dataset's mrsinmrs.json and a curated
literature T1 value (mrsiprep/config/t1_literature.json). This
is "literature" mode: one factor per metabolite, not per-voxel -- a future
voxelwise mode would require a measured B1+ map, which mrsiprep does not
currently ingest.

Only active when config.t1_correction == "literature"; a config with the
default "none" never calls into this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from mrsiprep.config.t1_values import METABOLITE_T1_VALUES
from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.utils.images import load_3d_data, save_nifti
from mrsiprep.utils.tables import write_tsv

_TR_KEYS = ("RepetitionTime", "TR")
_FLIP_KEYS = ("FlipAngle", "ExcitationFlipAngle")
_FIELD_KEYS = ("MagneticFieldStrength", "FieldStrength")
_TR_PLAUSIBLE_RANGE_S = (0.05, 20.0)
_MRSINMRS_URL = "https://doi.org/10.1002/nbm.4484"


class T1CorrectionError(RuntimeError):
    """Raised when T1 saturation correction cannot be applied safely."""


@dataclass
class AcquisitionParams:
    tr_s: float
    flip_deg: float
    field_strength_t: float
    tr_source_key: str
    flip_source_key: str
    field_source_key: str


def ernst_saturation_factor(tr_s: float, flip_deg: float, t1_s: float) -> float:
    """1 / (S/S0) for the spoiled steady-state signal equation.

    Multiplying a raw fitted amplitude by this factor estimates the fully
    relaxed (T1-recovered) amplitude.
    """
    alpha = math.radians(flip_deg)
    e1 = math.exp(-tr_s / t1_s)
    numerator = 1 - math.cos(alpha) * e1
    denominator = math.sin(alpha) * (1 - e1)
    if denominator <= 0:
        raise T1CorrectionError(
            f"Non-physical saturation factor for tr_s={tr_s}, flip_deg={flip_deg}, t1_s={t1_s} "
            "(sin(flip)*(1-exp(-TR/T1)) <= 0)."
        )
    return numerator / denominator


def resolve_metabolite_t1(metabolite: str, field_strength_t: float) -> dict:
    """Exact lookup against METABOLITE_T1_VALUES only.

    Deliberately does NOT consult mrsiprep.config.defaults.METABOLITE_ALIASES:
    that table is a fuzzy fallback for locating input files (e.g. accepting
    NAANAAG when tNAA was requested), which is the wrong behavior here --
    NAA and tNAA don't share a T1, so silently reusing one metabolite's T1
    for a differently-named one would introduce a real, silent bias. Raises
    on any metabolite not present as an exact key, on a "todo" or missing-T1
    entry, and on any field strength without an exact curated entry (no
    interpolation/extrapolation across field strengths).
    """
    entries = METABOLITE_T1_VALUES.get(metabolite)
    if entries is None:
        supported = ", ".join(sorted(METABOLITE_T1_VALUES))
        raise T1CorrectionError(
            f"No literature T1 database entry for metabolite '{metabolite}'. "
            f"Supported metabolites: {supported}. Metabolite aliasing is not "
            "applied for T1 lookup -- request the exact metabolite name or "
            "curate a new mrsiprep/config/t1_literature.json entry."
        )
    entry = entries.get(field_strength_t)
    if entry is None:
        supported_fields = ", ".join(str(f) for f in sorted(entries))
        raise T1CorrectionError(
            f"No literature T1 value for metabolite '{metabolite}' at "
            f"{field_strength_t}T. Curated field strengths: {supported_fields}. "
            "Interpolation/extrapolation across field strengths is not "
            "supported -- add a citation-backed entry for this field "
            "strength, or use --t1-correction none."
        )
    if entry["status"] == "todo" or entry["t1_s"] is None:
        raise T1CorrectionError(
            f"Literature T1 value for metabolite '{metabolite}' at "
            f"{field_strength_t}T is not yet curated (status={entry['status']!r}). "
            f"See mrsiprep/config/t1_literature.json: {entry['source']}"
        )
    return entry


def resolve_acquisition_params(mrsinmrs_resolved: dict | None) -> AcquisitionParams:
    """Validate TR/flip angle/field strength from a resolved MRSinMRS dict.

    MRSinMRS (Lin et al. 2021) enforces no fixed schema for parameter names,
    so this checks a small whitelist of recognized spellings per parameter
    rather than assuming a single key name. Raises if a required parameter
    is entirely absent, if multiple recognized spellings disagree, or if a
    value falls outside a physically plausible range.
    """
    if not mrsinmrs_resolved:
        raise T1CorrectionError(
            "--t1-correction literature requires a dataset-level mrsinmrs.json "
            f"with TR/FlipAngle/MagneticFieldStrength (see {_MRSINMRS_URL}), "
            "but none was found for this recording."
        )
    tr_s, tr_key = _resolve_field(mrsinmrs_resolved, _TR_KEYS, "TR")
    if not (_TR_PLAUSIBLE_RANGE_S[0] <= tr_s <= _TR_PLAUSIBLE_RANGE_S[1]):
        raise T1CorrectionError(
            f"mrsinmrs.json '{tr_key}'={tr_s} is outside the plausible TR range "
            f"{_TR_PLAUSIBLE_RANGE_S} seconds -- check units (TR must be in seconds)."
        )
    flip_deg, flip_key = _resolve_field(mrsinmrs_resolved, _FLIP_KEYS, "FlipAngle")
    if not (0 < flip_deg <= 180):
        raise T1CorrectionError(f"mrsinmrs.json '{flip_key}'={flip_deg} is outside the plausible 0-180 degree range.")
    field_t, field_key = _resolve_field(mrsinmrs_resolved, _FIELD_KEYS, "MagneticFieldStrength")
    return AcquisitionParams(
        tr_s=tr_s,
        flip_deg=flip_deg,
        field_strength_t=field_t,
        tr_source_key=tr_key,
        flip_source_key=flip_key,
        field_source_key=field_key,
    )


def _resolve_field(resolved: dict, keys: tuple[str, ...], label: str) -> tuple[float, str]:
    present = [(key, resolved[key]) for key in keys if key in resolved]
    if not present:
        raise T1CorrectionError(
            f"mrsinmrs.json is missing a recognized '{label}' field (looked for "
            f"{', '.join(keys)}). Add it under CommonMetadata or the recording's "
            f"Recordings entry -- see {_MRSINMRS_URL}."
        )
    distinct_values = {float(value) for _, value in present}
    if len(distinct_values) > 1:
        conflicting = ", ".join(f"{key}={value}" for key, value in present)
        raise T1CorrectionError(f"mrsinmrs.json has conflicting values for '{label}': {conflicting}. Resolve the ambiguity before using --t1-correction literature.")
    key, value = present[0]
    return float(value), key


def apply_t1_correction(
    config,
    subject: str,
    session: str | None,
    metabolite_maps: dict[str, Path],
    acquisition_params: AcquisitionParams,
    water_status: str,
) -> tuple[dict[str, Path], list[dict], Path]:
    """Multiply each metabolite map by its literature-derived saturation factor.

    Writes a per-recording confounds/*_desc-t1corr.tsv summary (one row per
    metabolite: T1/TR/flip/factor/sensitivity), mirroring how
    mrsiprep.mrsi.quality.make_quality_masks writes its own summary TSV.
    Returns the corrected map paths, the same summary rows (for provenance),
    and the summary TSV path.
    """
    corrected: dict[str, Path] = {}
    summary_rows: list[dict] = []
    warnings: list[str] = []
    if water_status == "unknown":
        warnings.append("Water-referencing status unknown; correction applied to metabolite T1 only.")
    for met, path in metabolite_maps.items():
        out = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", met=met, desc="signalt1corr", suffix_override="mrsi")
        entry = resolve_metabolite_t1(met, acquisition_params.field_strength_t)
        factor = ernst_saturation_factor(acquisition_params.tr_s, acquisition_params.flip_deg, entry["t1_s"])
        sensitivity = {}
        if entry["t1_sd_s"] is not None:
            sensitivity = {
                "factor_at_t1_minus_sd": ernst_saturation_factor(acquisition_params.tr_s, acquisition_params.flip_deg, entry["t1_s"] - entry["t1_sd_s"]),
                "factor_at_t1_plus_sd": ernst_saturation_factor(acquisition_params.tr_s, acquisition_params.flip_deg, entry["t1_s"] + entry["t1_sd_s"]),
            }
        summary_rows.append(
            {
                "metabolite": met,
                "t1_s": entry["t1_s"],
                "t1_sd_s": entry["t1_sd_s"],
                "tr_s": acquisition_params.tr_s,
                "flip_deg": acquisition_params.flip_deg,
                "field_strength_t": acquisition_params.field_strength_t,
                "saturation_factor": factor,
                "source": entry["source"],
                "doi": entry["doi"],
                "status": entry["status"],
                "water_status": water_status,
                **sensitivity,
            }
        )
        if out.exists() and not (config.overwrite_t1corr or config.overwrite):
            corrected[met] = out
            continue
        img, data = load_3d_data(path, dtype=np.float32, label=f"{met} map")
        finite = np.isfinite(data)
        result = data.copy()
        result[finite] = result[finite] * factor
        corrected[met] = save_nifti(result.astype(np.float32), img, out, dtype=np.float32)
    for row in summary_rows:
        row["warnings"] = "; ".join(warnings)
    summary = mrsi_derivative(config.derivative_dir, subject, session, desc="t1corr", suffix_override="tsv")
    write_tsv(summary_rows, summary)
    return corrected, summary_rows, summary

"""Per-metabolite signal-weighted leakage QC.

Reuses the same metric used to compare registration backends
(docs/benchmarks.md "Registration Frameworks" benchmark): at each
quality-passing voxel (CRLB <= ``config.crlb_max``) of a resampled
metabolite map, sum the signal magnitude; leakage is the fraction of
that total signal mass that falls outside the reference brain mask.
Weighting by signal magnitude (rather than a raw voxel count) avoids
over-penalizing thin, near-zero registration/interpolation boundary
artifacts while still flagging real signal displaced outside the brain.

Computed against whichever resampled space(s) the run actually produced:
T1w (opt-in, ``--output-mrsi-t1w``) against the T1w reference brain mask,
and/or MNI152 (the default ``--output-spaces`` target) against
nilearn's standard MNI152 brain mask, resampled onto the transformed
maps' own grid.
"""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
from nibabel.processing import resample_from_to

from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.utils.images import load_3d_data
from mrsiprep.utils.tables import write_tsv

_CRLB_PREFIX = "crlb-"
_NON_METABOLITE_KEYS = {"snr", "fwhm"}


def write_signal_leakage_qc(
    config,
    subject: str,
    session: str | None,
    transformed: dict[str, dict[str, Path]] | None,
    brain_mask_t1: Path | None,
) -> Path | None:
    """Writes a `desc-leakageqc` TSV (one row per space/metabolite) into
    `confounds/`, or returns None if no resampled space with a reference
    brain mask is available."""
    transformed = transformed or {}
    rows: list[dict] = []

    t1_maps = transformed.get("T1w")
    if t1_maps and brain_mask_t1 is not None and Path(brain_mask_t1).exists():
        outside_t1 = ~(load_3d_data(brain_mask_t1, dtype=np.float32, label="T1w reference brain mask")[1] > 0.5)
        rows.extend(_leakage_rows("T1w", t1_maps, outside_t1, config.crlb_max))

    mni_maps = transformed.get("MNI152NLin2009cAsym")
    if mni_maps:
        reference_met = next(iter(_metabolites(mni_maps)), None)
        if reference_met is not None:
            from nilearn import datasets

            mni_img = nib.load(str(mni_maps[reference_met]))
            mni_brain_mask = resample_from_to(datasets.load_mni152_brain_mask(), mni_img, order=0)
            outside_mni = ~(np.asarray(mni_brain_mask.dataobj) > 0.5)
            rows.extend(_leakage_rows("MNI152NLin2009cAsym", mni_maps, outside_mni, config.crlb_max))

    if not rows:
        return None

    out = mrsi_derivative(config.derivative_dir, subject, session, desc="leakageqc", suffix_override="tsv")
    write_tsv(rows, out)
    return out


def _metabolites(space_maps: dict[str, Path]) -> list[str]:
    return sorted(
        met
        for met in space_maps
        if not met.startswith(_CRLB_PREFIX) and met not in _NON_METABOLITE_KEYS and not met.startswith("spikemask-")
    )


def _leakage_rows(space: str, space_maps: dict[str, Path], outside_brain: np.ndarray, crlb_max: float) -> list[dict]:
    crlb_maps = {key[len(_CRLB_PREFIX) :]: path for key, path in space_maps.items() if key.startswith(_CRLB_PREFIX)}
    rows = []
    for met in _metabolites(space_maps):
        signal = load_3d_data(space_maps[met], dtype=np.float32, label=f"{met} {space} map")[1]
        quality = np.isfinite(signal)
        crlb_path = crlb_maps.get(met)
        if crlb_path is not None and Path(crlb_path).exists():
            crlb = load_3d_data(crlb_path, dtype=np.float32, label=f"{met} {space} CRLB map")[1]
            quality &= np.isfinite(crlb) & (crlb <= crlb_max)
        total_mass = float(np.abs(signal[quality]).sum())
        leakage_mass = float(np.abs(signal[quality & outside_brain]).sum())
        rows.append(
            {
                "space": space,
                "metabolite": met,
                "n_quality_voxels": int(quality.sum()),
                "total_signal_mass": total_mass,
                "leakage_signal_mass": leakage_mass,
                "leakage_fraction": leakage_mass / total_mass if total_mass > 0 else np.nan,
                "leakage_percent": 100.0 * leakage_mass / total_mass if total_mass > 0 else np.nan,
            }
        )
    return rows

"""Per-metabolite alignment montages (T1w-space / Template-space alignment tabs).

The alignment tabs' main figure (:func:`mrsiprep.reports.slices.render_multi_slice_triplanar_svg_flicker`)
only shows the reference metabolite (``config.ref_met``), since that is the
map used to drive the MRSI<->T1w/MNI registration itself. The other
metabolites were resampled with the same transform
(:func:`mrsiprep.mrsi.resampling.transform_mrsi_maps` always resamples every
metabolite, not just the reference), so this module adds one equally-spaced
axial montage per metabolite below the main figure -- same presentation as
the MRSI Raw/PVC tabs (:mod:`mrsiprep.reports.mrsi_raw_overview`,
:mod:`mrsiprep.reports.mrsi_pvc_overview`) -- so every metabolite's alignment
can be spot-checked, not just the reference's.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mrsiprep.io.naming import coverage_report_dir, qc_report_derivative
from mrsiprep.reports.slices import load_canonical_data, render_axial_overlay_montage

_CMAP = "magma"


def build_alignment_metabolite_sections(
    config,
    subject: str,
    session: str | None,
    space: str,
    background: np.ndarray,
    resampled_maps: dict[str, Path],
) -> list[tuple[str, str]]:
    """Returns one (heading, body_html) section per metabolite: an axial
    montage of that metabolite's ``space``-space map overlaid on
    ``background`` (the same anatomy array the main alignment figure uses).

    ``resampled_maps`` is the ``space`` entry of :func:`transform_mrsi_maps`'s
    output (e.g. ``transformed.get("T1w", {})``) -- besides every metabolite,
    it also carries quality-map entries under other key patterns
    (``crlb-*``, ``snr``, ``fwhm``, ``spikemask-*``), so this restricts to
    keys in ``config.metabolites`` rather than every key present. Metabolites
    whose resampled map doesn't exist (not requested, or resampling failed)
    are skipped rather than shown blank.
    """
    out = qc_report_derivative(config.derivative_dir, subject, session, "registration")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    metabolites = sorted(met for met in (config.metabolites or []) if met in (resampled_maps or {}))
    if not metabolites:
        return []

    sections: list[tuple[str, str]] = [(
        "Per-metabolite alignment",
        "<p>Each metabolite's map resampled into this space, overlaid on the same anatomy as the figure "
        "above, at equally-spaced axial slices.</p>",
    )]
    for met in metabolites:
        met_path = resampled_maps.get(met)
        if met_path is None or not Path(met_path).exists():
            continue
        overlay = load_canonical_data(met_path)
        montage_png = figures_dir / f"{out.stem}_space-{space}_met-{met}_align-slices.png"
        render_axial_overlay_montage(background, overlay, montage_png, label=met, overlay_cmap=_CMAP)
        sections.append((f"Metabolite: {met}", f"<img src='figures/{montage_png.name}'>"))

    return sections

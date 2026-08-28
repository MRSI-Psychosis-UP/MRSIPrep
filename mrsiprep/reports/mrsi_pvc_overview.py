"""Partial-volume-corrected MRSI maps (MRSI PVC tab).

Deliberately the same presentation as the MRSI Raw QC tab -- one
equally-spaced axial montage per metabolite -- so the two tabs can be compared
directly by flipping between them. The slice indices match for free: both tabs
derive them from the volume's own z-extent via
:func:`mrsiprep.reports.mrsi_raw_overview._equally_spaced_slices`, and the PVC
maps live on the same native MRSI grid as the raw maps.

Only built when PVC actually ran; ``--no-pvc`` leaves the tab out entirely
rather than showing maps identical to the uncorrected ones.
"""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.naming import coverage_report_dir, qc_report_derivative
from mrsiprep.reports.mrsi_raw_overview import _render_slice_montage
from mrsiprep.reports.slices import load_canonical_data


def build_mrsi_pvc_sections(
    config,
    subject: str,
    session: str | None,
    pvc_maps: dict[str, Path],
    reference_maps: dict[str, Path] | None = None,
) -> list[tuple[str, str]]:
    """Returns the MRSI PVC tab's (heading, body_html) sections.

    ``reference_maps`` (the pre-PVC maps) only sets each montage's intensity
    scaling, so a metabolite whose scale PVC changed is still readable rather
    than saturating or vanishing.
    """
    out = qc_report_derivative(config.derivative_dir, subject, session, "mrsi-pvc")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    metabolites = sorted(pvc_maps or {})
    if not metabolites:
        return [("Partial-volume-corrected maps", "<p>No partial-volume-corrected maps available.</p>")]

    sections: list[tuple[str, str]] = [(
        "Partial-volume correction",
        "<p>Partial-volume-corrected metabolite maps, on the native MRSI grid, at the same "
        "slices as the MRSI Raw QC tab so the two can be compared directly.</p>",
    )]
    for met in metabolites:
        pvc_path = pvc_maps[met]
        if not Path(pvc_path).exists():
            continue
        pvc_data = load_canonical_data(pvc_path)
        scale_source = (reference_maps or {}).get(met)
        scale_data = load_canonical_data(scale_source) if scale_source and Path(scale_source).exists() else pvc_data
        montage_png = figures_dir / f"{out.stem}_met-{met}_pvc-slices.png"
        _render_slice_montage(pvc_data, scale_data, montage_png, label=f"{met} (PVC)")
        sections.append((f"Metabolite: {met}", f"<img src='figures/{montage_png.name}'>"))

    return sections

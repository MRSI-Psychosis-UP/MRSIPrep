"""Tissue segmentation QC section (Anatomical tab of the combined report)."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.naming import coverage_report_dir, qc_report_derivative
from mrsiprep.reports.slices import load_canonical_data, render_triplanar_png, triplanar_slices


def build_tissue_qc_sections(
    config,
    subject: str,
    session: str | None,
    raw_t1: Path,
    dseg_path: Path | None,
    probseg_paths: dict[str, Path] | None = None,
) -> list[tuple[str, str]]:
    """Returns the Anatomical tab's (heading, body_html) sections."""
    out = qc_report_derivative(config.derivative_dir, subject, session, "tissue")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    t1_data = load_canonical_data(raw_t1)
    t1_slices = triplanar_slices(t1_data)
    sections: list[tuple[str, str]] = []

    if dseg_path is not None and Path(dseg_path).exists():
        label_data = load_canonical_data(dseg_path)
        label_slices = triplanar_slices(label_data)
        label_png = figures_dir / f"{out.stem}_labels.png"
        render_triplanar_png(t1_slices, label_png, overlay_slices=label_slices, mode="outline")
        sections.append(("Tissue label outlines", f"<img src='figures/{label_png.name}'>"))
    else:
        sections.append(("Tissue label outlines", "<p>No tissue label image available for this tissue backend.</p>"))

    if probseg_paths:
        prob_blocks = []
        for tissue_class, prob_path in probseg_paths.items():
            if prob_path is None or not Path(prob_path).exists():
                continue
            prob_data = load_canonical_data(prob_path)
            prob_slices = triplanar_slices(prob_data)
            prob_png = figures_dir / f"{out.stem}_probseg-{tissue_class}.png"
            render_triplanar_png(t1_slices, prob_png, overlay_slices=prob_slices, mode="alpha", colorbar_label=f"{tissue_class} probability")
            prob_blocks.append(f"<div><h3>{tissue_class}</h3><img src='figures/{prob_png.name}'></div>")
        sections.append(("Tissue probability maps", "<div class='col'>" + "".join(prob_blocks) + "</div>" if prob_blocks else "<p>No tissue probability maps available.</p>"))
    else:
        sections.append(("Tissue probability maps", "<p>No tissue probability maps available.</p>"))

    return sections

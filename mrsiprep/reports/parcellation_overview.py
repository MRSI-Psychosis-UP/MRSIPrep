"""T1w-space parcellation outline QC report."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.naming import qc_report_derivative
from mrsiprep.reports.slices import html_page, load_canonical_data, render_triplanar_png, triplanar_slices


def write_parcellation_qc_report(
    config,
    subject: str,
    session: str | None,
    raw_t1: Path,
    atlas_t1: Path | None,
    labels_path: Path | None = None,
) -> Path:
    out = qc_report_derivative(config.derivative_dir, subject, session, "parcellation")
    out.parent.mkdir(parents=True, exist_ok=True)
    figures_dir = out.parent / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    sections: list[tuple[str, str]] = []
    if atlas_t1 is not None and Path(atlas_t1).exists():
        t1_data = load_canonical_data(raw_t1)
        atlas_data = load_canonical_data(atlas_t1)
        t1_slices = triplanar_slices(t1_data)
        atlas_slices = triplanar_slices(atlas_data)
        atlas_png = figures_dir / f"{out.stem}_outlines.png"
        render_triplanar_png(t1_slices, atlas_png, overlay_slices=atlas_slices, mode="outline")
        note = ""
        if labels_path is not None and Path(labels_path).exists():
            import pandas as pd

            n_regions = len(pd.read_csv(labels_path, sep="\t"))
            note = f"<p>{n_regions} regions.</p>"
        sections.append(("Parcellation outlines (T1w space)", note + f"<img src='figures/{atlas_png.name}'>"))
    else:
        sections.append(("Parcellation outlines (T1w space)", "<p>Atlas not available in T1w space for this configuration.</p>"))

    out.write_text(html_page(f"Parcellation QC: sub-{subject}" + (f" ses-{session}" if session else ""), sections), encoding="utf-8")
    return out

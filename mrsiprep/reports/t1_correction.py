"""T1 saturation correction before/after QC section (its own conditional tab)."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.naming import coverage_report_dir, qc_report_derivative
from mrsiprep.reports.slices import load_canonical_data, render_triplanar_png, triplanar_slices

METABOLITE_COLORMAPS = (
    "viridis", "plasma", "cividis", "cool", "spring", "summer",
    "autumn", "winter", "copper", "bone", "ocean", "terrain",
)


def build_t1_correction_qc_sections(
    config,
    subject: str,
    session: str | None,
    preproc_maps: dict[str, Path],
    corrected_maps: dict[str, Path],
    summary_rows: list[dict],
) -> list[tuple[str, str]]:
    """Returns the T1 correction tab's (heading, body_html) sections.

    Renders the per-metabolite factor table first, since the correction is
    a uniform scalar multiply -- before/after slices mainly demonstrate scale
    change, not spatial change, unlike the spike-filter QC section."""
    out = qc_report_derivative(config.derivative_dir, subject, session, "t1-correction")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    rows_by_met = {row["metabolite"]: row for row in summary_rows}
    header = "<tr><th>Metabolite</th><th>T1 (s)</th><th>TR (s)</th><th>Flip (deg)</th><th>Field (T)</th><th>Factor</th><th>Source</th><th>Status</th></tr>"
    body_rows = "".join(
        f"<tr><td>{row['metabolite']}</td><td>{row['t1_s']:.3f}</td><td>{row['tr_s']:.3f}</td>"
        f"<td>{row['flip_deg']:.1f}</td><td>{row['field_strength_t']:.1f}</td>"
        f"<td>{row['saturation_factor']:.4f}</td><td>{row['source']}</td><td>{row['status']}</td></tr>"
        for row in summary_rows
    )
    warnings = sorted({row.get("warnings") for row in summary_rows if row.get("warnings")})
    warning_html = "".join(f"<p><strong>Warning:</strong> {text}</p>" for text in warnings)
    table_html = f"<table>{header}{body_rows}</table>{warning_html}"
    sections: list[tuple[str, str]] = [("Saturation correction factors", table_html)]

    metabolites = [met for met in preproc_maps if met in corrected_maps]
    for index, met in enumerate(metabolites):
        cmap = METABOLITE_COLORMAPS[index % len(METABOLITE_COLORMAPS)]
        before_data = load_canonical_data(preproc_maps[met])
        after_data = load_canonical_data(corrected_maps[met])
        before_slices = triplanar_slices(before_data)
        after_slices = triplanar_slices(after_data)
        before_png = figures_dir / f"{out.stem}_met-{met}_before.png"
        after_png = figures_dir / f"{out.stem}_met-{met}_after.png"
        render_triplanar_png(before_slices, before_png, cmap=cmap, colorbar_label=met)
        render_triplanar_png(after_slices, after_png, cmap=cmap, colorbar_label=met)
        factor = rows_by_met.get(met, {}).get("saturation_factor")
        factor_note = f"<p>Factor: {factor:.4f}</p>" if factor is not None else ""
        sections.append((
            f"Metabolite: {met}",
            factor_note + "<div class='row'>"
            f"<div><h3>Before</h3><img src='figures/{before_png.name}'></div>"
            f"<div><h3>After</h3><img src='figures/{after_png.name}'></div>"
            "</div>",
        ))

    return sections

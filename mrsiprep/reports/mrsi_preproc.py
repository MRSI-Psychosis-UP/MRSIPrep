"""MRSI preprocessing (spike-repair filtering) before/after QC report."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.naming import qc_report_derivative
from mrsiprep.reports.slices import html_page, load_canonical_data, render_triplanar_png, triplanar_slices

METABOLITE_COLORMAPS = (
    "viridis", "plasma", "cividis", "cool", "spring", "summer",
    "autumn", "winter", "copper", "bone", "ocean", "terrain",
)


def write_mrsi_preproc_qc_report(
    config,
    subject: str,
    session: str | None,
    raw_maps: dict[str, Path],
    preproc_maps: dict[str, Path],
) -> Path:
    import numpy as np

    out = qc_report_derivative(config.derivative_dir, subject, session, "mrsi-preproc")
    out.parent.mkdir(parents=True, exist_ok=True)
    figures_dir = out.parent / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    metabolites = [met for met in raw_maps if met in preproc_maps]
    raw_data = {met: np.squeeze(load_canonical_data(raw_maps[met])) for met in metabolites}
    preproc_data = {met: np.squeeze(load_canonical_data(preproc_maps[met])) for met in metabolites}

    repaired_union = None
    for met in metabolites:
        repaired = ~np.isclose(raw_data[met], preproc_data[met])
        repaired_union = repaired if repaired_union is None else (repaired_union | repaired)

    if repaired_union is not None and repaired_union.any():
        center_ijk = tuple(int(round(coordinate)) for coordinate in np.argwhere(repaired_union).mean(axis=0))
        note = "<p>Slices centered on the centroid of all voxels repaired by spike/missing-voxel filtering, across all metabolites.</p>"
    else:
        center_ijk = None
        note = "<p>No voxels required repair for any metabolite; showing volume-center slices.</p>"

    sections: list[tuple[str, str]] = [("Filtering summary", note)]
    for index, met in enumerate(metabolites):
        cmap = METABOLITE_COLORMAPS[index % len(METABOLITE_COLORMAPS)]
        before_slices = triplanar_slices(raw_data[met], center_ijk)
        after_slices = triplanar_slices(preproc_data[met], center_ijk)
        before_png = figures_dir / f"{out.stem}_met-{met}_before.png"
        after_png = figures_dir / f"{out.stem}_met-{met}_after.png"
        render_triplanar_png(before_slices, before_png, cmap=cmap, colorbar_label=met)
        render_triplanar_png(after_slices, after_png, cmap=cmap, colorbar_label=met)
        sections.append((
            f"Metabolite: {met}",
            "<div class='row'>"
            f"<div><h3>Before</h3><img src='figures/{before_png.name}'></div>"
            f"<div><h3>After</h3><img src='figures/{after_png.name}'></div>"
            "</div>",
        ))

    out.write_text(html_page(f"MRSI preprocessing QC: sub-{subject}" + (f" ses-{session}" if session else ""), sections), encoding="utf-8")
    return out

"""MRSI preprocessing (spike-repair filtering) before/after QC section (Spike filter tab)."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.naming import coverage_report_dir, mrsi_derivative, qc_report_derivative
from mrsiprep.reports.slices import load_canonical_data, render_triplanar_png, triplanar_slices

# One fixed colormap for every metabolite's before/after pair, so panels are
# visually comparable across metabolites rather than each getting its own hue.
_MAP_CMAP = "viridis"


def _render_value_histogram(
    raw, preproc, out_path: Path, label: str, mask=None, xlabel_suffix: str = "", empty_message: str = "No voxels",
    require_nonzero_in_both: bool = False,
) -> Path:
    """Log-log histogram of before/after values, optionally restricted to a
    ``mask`` (e.g. only voxels ``get_spike_mask()`` flagged as spikes).
    ``mask=None`` covers every finite nonzero voxel in the whole image.

    ``require_nonzero_in_both=True`` additionally restricts to voxels that
    are nonzero in BOTH raw and preproc, rather than each panel selecting
    its own nonzero voxels independently -- needed for a fair whole-image
    before/after comparison, since ``biharmonic_repair()`` separately
    inpaints every exact-zero voxel inside the brain mask as a "missing"
    hole (unrelated to spike removal; can be the majority of the mask on
    acquisitions with a steep SNR falloff toward the slab edge). Without
    this, thousands of newly-filled near-zero voxels that were never really
    part of the signal to begin with dominate the "after" distribution's
    low end and make it look like real signal collapsed toward zero.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    out_path.parent.mkdir(parents=True, exist_ok=True)
    finite = np.isfinite(raw) & np.isfinite(preproc)
    if mask is not None:
        finite &= mask
    if require_nonzero_in_both:
        finite &= (raw > 0) & (preproc > 0)
    raw_vals = raw[finite & (raw > 0)]
    preproc_vals = preproc[finite & (preproc > 0)]

    fig, ax = plt.subplots(figsize=(7, 4))
    if raw_vals.size or preproc_vals.size:
        combined_max = max(raw_vals.max() if raw_vals.size else 0.0, preproc_vals.max() if preproc_vals.size else 0.0)
        combined_min = min(raw_vals.min() if raw_vals.size else combined_max, preproc_vals.min() if preproc_vals.size else combined_max)
        combined_min = max(combined_min, 1e-6)
        bins = np.geomspace(combined_min, max(combined_max, combined_min * 10), 40)
        if raw_vals.size:
            ax.hist(raw_vals, bins=bins, alpha=0.5, label="before", color="tab:red", edgecolor="darkred", linewidth=0.8)
        if preproc_vals.size:
            ax.hist(preproc_vals, bins=bins, alpha=0.5, label="after", color="tab:blue", edgecolor="darkblue", linewidth=0.8)
        ax.set_xscale("log")
    else:
        ax.text(0.5, 0.5, empty_message, ha="center", va="center", transform=ax.transAxes)
    ax.set_yscale("log")
    ax.set_xlabel(f"{label} value{xlabel_suffix} (log scale)")
    ax.set_ylabel("voxel count (log scale)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def build_mrsi_preproc_qc_sections(
    config,
    subject: str,
    session: str | None,
    raw_maps: dict[str, Path],
    preproc_maps: dict[str, Path],
) -> list[tuple[str, str]]:
    """Returns the Spike filter tab's (heading, body_html) sections."""
    import numpy as np

    out = qc_report_derivative(config.derivative_dir, subject, session, "mrsi-preproc")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    metabolites = [met for met in raw_maps if met in preproc_maps]
    raw_data = {met: np.squeeze(load_canonical_data(raw_maps[met])) for met in metabolites}
    preproc_data = {met: np.squeeze(load_canonical_data(preproc_maps[met])) for met in metabolites}

    spike_masks: dict[str, "np.ndarray | None"] = {}
    spike_counts: dict[str, int | None] = {}
    for met in metabolites:
        spike_path = mrsi_derivative(config.derivative_dir, subject, session, space="MRSI", met=met, desc="spikemask", suffix_override="mask")
        if spike_path.exists():
            mask = np.squeeze(load_canonical_data(spike_path)) > 0.5
            spike_masks[met] = mask
            spike_counts[met] = int(np.count_nonzero(mask))
        else:
            spike_masks[met] = None
            spike_counts[met] = None

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

    summary_rows = "".join(
        f"<tr><td>{met}</td><td>{spike_counts[met] if spike_counts[met] is not None else 'n/a'}</td></tr>" for met in metabolites
    )
    summary_table = f"<table><tr><th>Metabolite</th><th>Spike voxels detected</th></tr>{summary_rows}</table>"
    sections: list[tuple[str, str]] = [("Filtering summary", note + summary_table)]
    for met in metabolites:
        before_slices = triplanar_slices(raw_data[met], center_ijk)
        after_slices = triplanar_slices(preproc_data[met], center_ijk)
        # Shared vmin/vmax across before/after so the same colormap encodes
        # the same intensity range in both panels, making the comparison
        # apples-to-apples rather than each panel auto-scaling separately.
        # vmax is a high percentile of the AFTER (filtered) data, not the
        # raw max: the whole point of this tab is to show spikes that were
        # orders of magnitude above real tissue signal, so using the raw
        # map's max as vmax would let a single to-be-removed outlier spike
        # set the scale for both panels, crushing all the real brain signal
        # (and the fact that it's now gone) into an unreadable dark band.
        vmin = float(min(raw_data[met].min(), preproc_data[met].min()))
        finite_preproc = preproc_data[met][np.isfinite(preproc_data[met])]
        vmax = float(np.percentile(finite_preproc, 99.5)) if finite_preproc.size else float(preproc_data[met].max())
        vmax = max(vmax, vmin + 1e-6)
        before_png = figures_dir / f"{out.stem}_met-{met}_before.png"
        after_png = figures_dir / f"{out.stem}_met-{met}_after.png"
        render_triplanar_png(before_slices, before_png, cmap=_MAP_CMAP, colorbar_label=met, vmin=vmin, vmax=vmax)
        render_triplanar_png(after_slices, after_png, cmap=_MAP_CMAP, colorbar_label=met, vmin=vmin, vmax=vmax)
        spike_note = f"<p>Spike voxels detected: {spike_counts[met]}</p>" if spike_counts[met] is not None else ""
        body = (
            spike_note + "<div class='row'>"
            f"<div><h3>Before</h3><img src='figures/{before_png.name}'></div>"
            f"<div><h3>After</h3><img src='figures/{after_png.name}'></div>"
            "</div>"
        )
        whole_hist_png = figures_dir / f"{out.stem}_met-{met}_histogram-whole.png"
        _render_value_histogram(
            raw_data[met], preproc_data[met], whole_hist_png, label=met,
            xlabel_suffix=" (whole image)", empty_message="No positive voxels",
            require_nonzero_in_both=True,
        )
        hist_divs = f"<div><h4>Whole image</h4><img src='figures/{whole_hist_png.name}'></div>"
        spike_mask = spike_masks.get(met)
        if spike_mask is not None:
            spike_hist_png = figures_dir / f"{out.stem}_met-{met}_histogram-spikes.png"
            _render_value_histogram(
                raw_data[met], preproc_data[met], spike_hist_png, label=met, mask=spike_mask,
                xlabel_suffix=" at spike voxels", empty_message="No spike voxels detected",
            )
            hist_divs += f"<div><h4>Spike voxels only</h4><img src='figures/{spike_hist_png.name}'></div>"
        body += f"<div class='row'>{hist_divs}</div>"
        sections.append((f"Metabolite: {met}", body))

    return sections

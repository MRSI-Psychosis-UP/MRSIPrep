"""Raw (pre-pipeline) MRSI signal QC section (MRSI Raw QC tab).

A quick-look montage of the metabolite maps exactly as they arrived from
the upstream quantification toolchain, before any mrsiprep processing
(spike repair, PVC, registration) touches them -- lets the initial
acquisition/reconstruction quality be assessed independent of anything
mrsiprep itself might do to the data.
"""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.naming import coverage_report_dir, qc_report_derivative
from mrsiprep.reports.slices import load_canonical_data

N_SLICES = 10
_CMAP = "viridis"


def _center_weighted_indices(size: int, n_slices: int):
    """``n_slices`` indices spanning ``[0, size-1]``, denser near the
    center and sparser toward the edges -- a cosine warp of an otherwise
    even spacing, matching the fact that a 3D-MRSI slab's real, usable
    signal concentrates around its center while edge slices are mostly
    outside true acquisition coverage (SNR falls off sharply there), so
    the interesting range deserves more samples than the empty extremes.
    """
    import numpy as np

    if size <= 1:
        return np.zeros(1, dtype=int)
    linear = np.linspace(-1.0, 1.0, n_slices)
    # sign(x) * (1 - cos(pi*|x|/2)) rescales [-1, 1] so points cluster near
    # 0 and spread out near +-1, while endpoints stay fixed at +-1.
    warped = np.sign(linear) * (1.0 - np.cos(np.pi * np.abs(linear) / 2.0))
    positions = (warped + 1.0) / 2.0 * (size - 1)
    return np.unique(np.round(positions).astype(int))


def _equally_spaced_slices(volume_data, n_slices: int = N_SLICES, axis: int = 2):
    """Returns up to ``n_slices`` 2D slices taken at center-weighted indices
    along ``axis`` (default 2, i.e. axial on RAS-canonical data), skipping
    any slice that's entirely empty (common at the very edges of a padded
    grid), plus the index actually used for each."""
    import numpy as np

    size = volume_data.shape[axis]
    candidate_indices = _center_weighted_indices(size, n_slices)
    slices = []
    for index in candidate_indices:
        plane = np.take(volume_data, index, axis=axis)
        if not np.any(plane > 0):
            continue
        slices.append((int(index), np.rot90(plane)))
    return slices or [(int(candidate_indices[len(candidate_indices) // 2]), np.rot90(np.take(volume_data, candidate_indices[len(candidate_indices) // 2], axis=axis)))]


def _render_slice_montage(volume_data, preproc_data, out_path: Path, label: str) -> Path:
    """Renders equally-spaced axial slices of ``volume_data`` (the raw map)
    in a single row, with the color scale set from ``preproc_data`` (the
    filtered map) rather than the raw data's own max -- an unfiltered
    acquisition spike can be orders of magnitude above real tissue signal,
    and scaling to it would crush every slice's real anatomy into an
    unreadable dark band.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    out_path.parent.mkdir(parents=True, exist_ok=True)
    slices = _equally_spaced_slices(volume_data)

    finite_preproc = preproc_data[np.isfinite(preproc_data)]
    vmax = float(np.percentile(finite_preproc, 99.5)) if finite_preproc.size else float(np.nanmax(volume_data))
    vmin = 0.0
    vmax = max(vmax, vmin + 1e-6)

    n = len(slices)
    fig, axes = plt.subplots(1, n, figsize=(1.8 * n, 2.2), constrained_layout=True)
    if n == 1:
        axes = [axes]
    image = None
    for ax, (index, plane) in zip(axes, slices):
        image = ax.imshow(plane, cmap=_CMAP, vmin=vmin, vmax=vmax)
        ax.set_title(f"z={index}", fontsize=8)
        ax.axis("off")
    if image is not None:
        fig.colorbar(image, ax=axes, fraction=0.02, pad=0.02, label=label)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def build_mrsi_raw_qc_sections(
    config,
    subject: str,
    session: str | None,
    raw_maps: dict[str, Path],
    preproc_maps: dict[str, Path],
) -> list[tuple[str, str]]:
    """Returns the MRSI Raw QC tab's (heading, body_html) sections: one
    equally-spaced-slice montage per metabolite, straight from the
    unprocessed input maps."""
    out = qc_report_derivative(config.derivative_dir, subject, session, "mrsi-raw")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    metabolites = sorted(raw_maps)
    if not metabolites:
        return [("Raw metabolite maps", "<p>No raw MRSI metabolite maps available.</p>")]

    sections: list[tuple[str, str]] = []
    for met in metabolites:
        raw_data = load_canonical_data(raw_maps[met])
        preproc_path = preproc_maps.get(met)
        preproc_data = load_canonical_data(preproc_path) if preproc_path is not None else raw_data
        montage_png = figures_dir / f"{out.stem}_met-{met}_raw-slices.png"
        _render_slice_montage(raw_data, preproc_data, montage_png, label=met)
        sections.append((f"Metabolite: {met}", f"<img src='figures/{montage_png.name}'>"))

    return sections

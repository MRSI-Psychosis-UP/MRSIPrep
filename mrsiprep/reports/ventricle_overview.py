"""Ventricle visibility section (MRSI Raw QC tab, after the QC summary
table).

Rendering only: detection and Dice scoring live in
:mod:`mrsiprep.qc.ventricles`. This module picks one display slice shared by
all metabolites, draws the detected outlines on it, and, when the subject's own
ventricles were available, adds a bar chart of each metabolite's Dice and
writes the scores to a ``desc-ventricleqc`` TSV.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mrsiprep.io.naming import coverage_report_dir, mrsi_derivative, qc_report_derivative
from mrsiprep.qc.ventricles import DICE_GOOD as VENTRICLE_DICE_GOOD
from mrsiprep.qc.ventricles import run_ventricle_qc, write_ventricle_qc_tsv

# Top of the bar colour scale (full green). At ~5 mm the lateral ventricles are
# only a few voxels thick, so even a clean map rarely exceeds Dice ~0.3-0.4;
# ending the scale at 1.0 would leave every good scan pale yellow.
VENTRICLE_DICE_FULL_GREEN = 0.5
MAX_MONTAGE_COLUMNS = 5


def _prior_slice_bias(prior_roi: np.ndarray) -> np.ndarray:
    """Gaussian weight over z, peaked where the warped prior actually puts
    the ventricles.

    Detection can pick up dark voxels far from the ventricles -- the
    inferior slices where the head leaves the excitation volume are the
    usual culprit, and they can carry more sub-threshold voxels than the
    ventricles themselves. Weighting by the prior's own centre of mass
    keeps the search near the expected location. Anchoring to the prior
    rather than to the middle of the array matters because the MRSI FOV is
    routinely asymmetric about the brain, so "the middle slice" and "where
    ventricles are" are not the same index.
    """
    counts = prior_roi.sum(axis=(0, 1)).astype(float)
    n_slices = prior_roi.shape[2]
    z = np.arange(n_slices, dtype=float)
    total = counts.sum()
    if total <= 0:
        center = (n_slices - 1) / 2.0
        sigma = max(n_slices / 6.0, 1.0)
    else:
        center = float((counts * z).sum() / total)
        spread = float(np.sqrt((counts * (z - center) ** 2).sum() / total))
        # Floor the width generously. The placement is a coarse bounding-box
        # affine, so it can sit a couple of slices off; a narrow prior would
        # otherwise turn this into a hard gate that pins the montage to a
        # mis-placed centre. At sigma=2 a slice 2 away is only mildly
        # penalised (x0.61) while one 5 away is strongly suppressed (x0.04),
        # which is the intended shape: break ties, never override the data.
        sigma = max(spread, 2.0)
    return np.exp(-0.5 * ((z - center) / sigma) ** 2)


def _slice_counts(detected: np.ndarray) -> np.ndarray:
    """Raw detected-voxel count per axial slice."""
    return detected.sum(axis=(0, 1)).astype(float)


def _consensus_slice(counts: list[np.ndarray], biases: list[np.ndarray], min_voxels: int = 3) -> int | None:
    """One slice index for the whole montage, agreed across metabolites.

    Letting each metabolite pick its own argmax meant a single noisy map
    could land on an unrelated slice, so panels that should be directly
    comparable were not: the same recording rendered CrPCr at z=11 and
    GPCPCh at z=6.

    Each metabolite votes with its prior-biased profile normalised by its
    own peak, so a high-SNR metabolite cannot outvote the rest and the
    winner is the slice most metabolites agree on rather than the one with
    the largest absolute count.

    The ``min_voxels`` floor is applied to the *raw* counts, not the biased
    ones, so the bias only ever reorders candidate slices -- it can never
    manufacture a detection that isn't in the data. Returns ``None`` when no
    metabolite reaches ``min_voxels`` at the winning slice, preserving the
    previous "absent is itself informative" behaviour.
    """
    if not counts:
        return None
    votes = np.zeros(len(counts[0]), dtype=float)
    for count, bias in zip(counts, biases):
        weighted = count * bias
        peak = weighted.max()
        if peak > 0:
            votes += weighted / peak
    if votes.max() <= 0:
        return None
    best = int(np.argmax(votes))
    if max(float(count[best]) for count in counts) < min_voxels:
        return None
    return best


def _render_ventricle_montage(panels: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]], z: int, out_path: Path) -> Path:
    """One combined figure, one subplot per metabolite, at most
    ``MAX_MONTAGE_COLUMNS`` per row -- e.g. 9 metabolites lays out as 5
    columns x 2 rows -- rather than a separate standalone image per
    metabolite.

    Every panel is drawn at the same slice ``z``, so the montage compares
    metabolites rather than compares slices; the index is stated once in the
    figure title instead of per panel.
    """
    import math

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = len(panels)
    n_cols = min(n, MAX_MONTAGE_COLUMNS)
    n_rows = math.ceil(n / MAX_MONTAGE_COLUMNS)

    fig, axes = plt.subplots(n_rows, n_cols, figsize=(2.6 * n_cols, 2.6 * n_rows), constrained_layout=True, squeeze=False)
    for index, (met, signal, prior_roi, detected) in enumerate(panels):
        ax = axes[index // n_cols][index % n_cols]
        finite = signal[np.isfinite(signal) & (signal > 0)]
        vmax = float(np.percentile(finite, 99)) if finite.size else float(np.nanmax(signal))
        ax.imshow(np.rot90(signal[:, :, z]), cmap="viridis", vmin=0, vmax=max(vmax, 1e-6))
        ax.contour(np.rot90(prior_roi[:, :, z]), levels=[0.5], colors="white", linewidths=1.0, linestyles="dashed")
        ax.contour(np.rot90(detected[:, :, z]), levels=[0.5], colors="red", linewidths=1.6)
        ax.set_title(met, fontsize=9)
        ax.axis("off")
    fig.suptitle(f"consensus slice z={z}", fontsize=10)

    for index in range(n, n_rows * n_cols):
        axes[index // n_cols][index % n_cols].axis("off")

    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def _render_dice_bars(dice: dict[str, float], out_path: Path) -> Path:
    """Bar chart of Dice per metabolite plus the median across metabolites.

    Colour runs from deep red (0) through amber at :data:`VENTRICLE_DICE_GOOD`
    to deep green at :data:`VENTRICLE_DICE_FULL_GREEN` and above; the
    threshold is also drawn as a dashed line and every bar carries its value,
    so the reading never depends on colour alone.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    names = list(dice) + [f"median (N={len(dice)})"]
    values = list(dice.values()) + [float(np.median(list(dice.values())))]
    norm = TwoSlopeNorm(vmin=0.0, vcenter=VENTRICLE_DICE_GOOD, vmax=VENTRICLE_DICE_FULL_GREEN)
    cmap = plt.get_cmap("RdYlGn")
    x = np.arange(len(names), dtype=float)
    x[-1] += 0.6  # set the summary bar apart from the metabolites

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(max(5.5, 0.6 * len(names) + 2.0), 3.2), constrained_layout=True)
    ax.bar(x, values, width=0.72, color=[cmap(norm(min(v, VENTRICLE_DICE_FULL_GREEN))) for v in values], edgecolor="#444", linewidth=[0.4] * len(dice) + [1.4])
    ax.axhline(VENTRICLE_DICE_GOOD, color="#444", linestyle="--", linewidth=1, label=f"good ≥ {VENTRICLE_DICE_GOOD:g}")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=8, handlelength=2.2)
    top = max(0.4, max(values) + 0.1)
    for xi, v in zip(x, values):
        ax.text(xi, v + 0.01 * top, f"{v:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x, names, rotation=45, ha="right", fontsize=8)
    ax.set_ylim(0, top)
    ax.set_xlim(x[0] - 0.6, x[-1] + 0.6)
    ax.set_ylabel("Dice with lateral ventricles", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    cb = fig.colorbar(sm, ax=ax, pad=0.01, fraction=0.04)
    cb.set_ticks([0, VENTRICLE_DICE_GOOD, VENTRICLE_DICE_FULL_GREEN])
    cb.ax.tick_params(labelsize=7)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def build_ventricle_qc_sections(
    config, subject: str, session: str | None, raw_maps: dict[str, Path], reference_ventricles: Path | None = None
) -> list[tuple[str, str]]:
    """The ventricle section of the MRSI Raw tab.

    Runs :func:`mrsiprep.qc.ventricles.run_ventricle_qc` and renders its
    result: every metabolite's detection on one shared slice and, when
    ``reference_ventricles`` (the subject's ventricles on the same native
    grid, see :func:`mrsiprep.qc.ventricles.ventricle_reference_mask`) is
    given, a Dice bar chart and TSV. Returns [] (no section, not an error)
    if FSL's standard-space data isn't available, since this is a
    supplementary check on top of the required per-metabolite montages
    above it, not a hard dependency.
    """
    result = run_ventricle_qc(raw_maps, reference_ventricles)
    if result is None:
        return []
    detections = result.detections
    # Metabolites acquired on different grids cannot share a slice index;
    # this is not expected within one recording, but silently rendering
    # mismatched indices would be worse than skipping the check.
    if detections and len({det.signal.shape for det in detections}) > 1:
        return []
    consensus_z = _consensus_slice([_slice_counts(det.detected) for det in detections], [_prior_slice_bias(det.prior) for det in detections])
    if not detections or (consensus_z is None and not result.dice):
        return []

    out = qc_report_derivative(config.derivative_dir, subject, session, "mrsi-raw")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    # Legend, not prose: the reader needs to know what each colour is and
    # which slice they are looking at. The interpretation ("a ragged outline
    # means X") was several sentences of text that told an MRSI reader what
    # the picture already shows.
    # Swatches are CSS borders rather than box-drawing characters, which
    # depend on the reader's font having them.
    swatch = (
        "display:inline-block;width:24px;height:0;vertical-align:middle;margin-right:4px;border-top:{}"
    )
    body = ""
    if consensus_z is not None:
        png_path = figures_dir / f"{out.stem}_ventricle-qc.png"
        _render_ventricle_montage([(det.metabolite, det.signal, det.prior, det.detected) for det in detections], consensus_z, png_path)
        body += (
            "<p style='margin:0 0 0.6em'>"
            f"<span style='{swatch.format('3px solid #d62728')}'></span>detected ventricle"
            "<span style='display:inline-block;width:1.6em'></span>"
            f"<span style='{swatch.format('2px dashed #bbb')}'></span>MNI prior"
            "<span style='display:inline-block;width:1.6em'></span>"
            f"<span style='color:#666'>native MRSI space, pre-coregistration &middot; all metabolites at z={consensus_z}</span>"
            "</p>"
            f"<img src='figures/{png_path.name}'>"
        )
    else:
        body += "<p style='margin:0 0 0.6em;color:#666'>No ventricle-like darkening detected in any metabolite.</p>"

    if result.dice:
        write_ventricle_qc_tsv(result, mrsi_derivative(config.derivative_dir, subject, session, desc="ventricleqc", suffix_override="tsv"))
        bars = _render_dice_bars({row.metabolite: row.dice for row in result.dice}, figures_dir / f"{out.stem}_ventricle-dice.png")
        body += (
            "<p style='margin:1em 0 0.6em'>"
            f"<b>Dice with the subject's lateral ventricles</b> &middot; median {result.median_dice:.2f} "
            f"<span style='color:#666'>(SynthSeg, moved to MRSI space by the MRSI&rarr;T1w transform; "
            f"green from {VENTRICLE_DICE_GOOD:g})</span>"
            "</p>"
            f"<img src='figures/{bars.name}'>"
        )
    return [("Ventricle visibility", body)]

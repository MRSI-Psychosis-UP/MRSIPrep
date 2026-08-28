"""Parcelwise MRSI figures: anatomical coverage and per-metabolite CRLB quality.

Both are derived from the parcel-QC TSV written by
:func:`mrsiprep.reports.parcel_qc.write_parcel_qc`. The coverage montage uses
the native-MRSI-space parcel atlas; the CRLB glass-brain figures use the
T1w-space atlas resampled into MNI space (glass-brain projection requires
MNI space). Saved into the subject/session ``reports/coverage/figures/``
folder next to the HTML report so it can embed them with relative paths.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from mrsiprep.io.naming import coverage_figure_derivative

# A parcel's metabolite estimate is treated as reliable when its mean CRLB is
# below this percentage (green); at or above it, unreliable (red).
CRLB_QUALITY_THRESHOLD = 20.0


def _atlas_canonical(path: Path) -> np.ndarray:
    import nibabel as nib

    return np.rint(nib.as_closest_canonical(nib.load(str(path))).get_fdata()).astype(np.int32).squeeze()


def _value_volume(atlas: np.ndarray, parcel_to_value: dict[int, float]) -> np.ndarray:
    out = np.zeros(atlas.shape, dtype=np.float32)
    for parcel_id, value in parcel_to_value.items():
        if value is None or (isinstance(value, float) and np.isnan(value)):
            continue
        out[atlas == parcel_id] = value
    return out



#: Axial slices per montage, matching the MRSI Raw QC tab so the two read the
#: same way.
N_SLICES = 10


def _axial_slice_indices(volume: np.ndarray, n_slices: int = N_SLICES) -> list[int]:
    """``n_slices`` indices spanning the slices that actually contain data.

    Spanning the whole array instead would spend half the montage on the empty
    padding above and below the brain, which is what makes a fixed linspace
    over the raw extent look mostly blank.
    """
    occupied = np.flatnonzero(np.any(volume != 0, axis=(0, 1)))
    if occupied.size == 0:
        low, high = 0, volume.shape[2] - 1
    else:
        low, high = int(occupied[0]), int(occupied[-1])
    if high <= low:
        return [low] * n_slices
    return [int(round(value)) for value in np.linspace(low, high, n_slices)]


def _render_axial_montage(
    out_path: Path,
    value_volume: np.ndarray,
    indices: list[int],
    title: str,
    cmap: str,
    vmin: float,
    vmax: float,
    underlay: np.ndarray | None = None,
    colorbar_label: str | None = None,
    alpha: float = 1.0,
) -> Path:
    """One row of axial slices, values over an optional greyscale underlay."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, len(indices), figsize=(1.55 * len(indices), 2.1), constrained_layout=True)
    axes = np.atleast_1d(axes)
    image = None
    for ax, index in zip(axes, indices):
        if underlay is not None:
            under = np.rot90(underlay[:, :, min(index, underlay.shape[2] - 1)])
            ax.imshow(under, cmap="gray", interpolation="nearest")
        plane = np.rot90(value_volume[:, :, index])
        image = ax.imshow(
            np.ma.masked_invalid(np.ma.masked_equal(plane, 0.0)),
            cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest", alpha=alpha,
        )
        ax.set_title(f"z={index}", fontsize=7)
        ax.axis("off")
    if colorbar_label and image is not None:
        fig.colorbar(image, ax=axes.tolist(), shrink=0.75, label=colorbar_label)
    fig.suptitle(title, fontsize=9)
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def _render_axial_grid(
    out_path: Path,
    rows: list,
    indices: list,
    title: str,
    cmap: str,
    vmin: float,
    vmax: float,
    underlay: np.ndarray | None = None,
    alpha: float = 1.0,
) -> Path:
    """One figure, one row per label, the same slices across every row.

    A row per metabolite rather than a separate figure each: the point of the
    panel is to compare metabolites at identical anatomy, which side-by-side
    figures squeezed into a flex row cannot show.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_rows, n_cols = len(rows), len(indices)
    fig, axes = plt.subplots(
        n_rows, n_cols, figsize=(1.5 * n_cols, 1.7 * n_rows), squeeze=False, constrained_layout=True
    )
    for row_index, (label, volume) in enumerate(rows):
        for col_index, index in enumerate(indices):
            ax = axes[row_index][col_index]
            if underlay is not None:
                ax.imshow(
                    np.rot90(underlay[:, :, min(index, underlay.shape[2] - 1)]),
                    cmap="gray", interpolation="nearest",
                )
            plane = np.rot90(volume[:, :, index])
            ax.imshow(
                np.ma.masked_invalid(np.ma.masked_equal(plane, 0.0)),
                cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest", alpha=alpha,
            )
            ax.axis("off")
            if row_index == 0:
                ax.set_title(f"z={index}", fontsize=7)
        axes[row_index][0].axis("on")
        axes[row_index][0].set_xticks([])
        axes[row_index][0].set_yticks([])
        axes[row_index][0].set_ylabel(label, fontsize=8)
    fig.suptitle(title, fontsize=10)
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def write_parcel_coverage_figure(config, subject: str, session: str | None, atlas_mrsi: Path, parcel_qc_tsv: Path) -> Path | None:
    """Triplanar (coronal/axial/sagittal) heatmap of per-parcel MRSI anatomical coverage %.

    Rendered on the native MRSI acquisition grid (``atlas_mrsi``, the T1w
    atlas already warped into MRSI space for the coverage QC table) rather
    than the T1w grid: the T1w grid is typically much larger than, and
    asymmetrically padded around, the brain, which previously made the
    geometric array midpoint (and thus the coronal/axial slice) land outside
    the cerebrum even though most parcels had near-100% coverage.
    """
    df = pd.read_csv(parcel_qc_tsv, sep="\t")
    if df.empty or "anatomical_coverage_percent" not in df:
        return None
    per_parcel = df.groupby("parcel_id")["anatomical_coverage_percent"].first().to_dict()
    atlas = _atlas_canonical(atlas_mrsi)
    coverage = _value_volume(atlas, per_parcel)

    out = coverage_figure_derivative(config.derivative_dir, subject, session, desc="parcelcoverage")
    return _render_axial_montage(
        out,
        coverage,
        _axial_slice_indices(coverage),
        title="MRSI anatomical coverage (%)",
        cmap="viridis",
        # Pinned to the metric's real 0-100% range: coverage is often uniform,
        # and autoscaling a zero-variance field pads an arbitrary margin around
        # it (e.g. 90-110%), which reads as a bug at a glance.
        vmin=0.0,
        vmax=100.0,
        colorbar_label="coverage (%)",
    )


def _resample_atlas_to_mni(config, subject: str, session: str | None, atlas_t1: Path, t1_to_mni, mrsi_reference: Path | None = None) -> tuple[np.ndarray, "object"]:
    """Resample the (subject-space) T1w atlas into MNI space via the same
    T1w->MNI transform used for MRSI outputs, so glass-brain projection (which
    assumes MNI space) is actually aligned with its silhouette."""
    import nibabel as nib

    from mrsiprep.registration.transforms import apply_image_transform
    from mrsiprep.config.templates import template_t1w

    resolution = config.resolution_for("MNI152NLin2009cAsym", atlas_t1, mrsi_reference)
    template = template_t1w(resolution)
    # Subject/session-specific filename: this used to be one shared
    # `coverage_mni_atlas.nii.gz` path written by every recording, which
    # under `--nproc > 1` let two workers race on the same file mid-write
    # and corrupt it (surfaced as `ImageFileError: ... is not a gzip file`).
    ses_label = session or "none"
    out = config.work_dir / f"sub-{subject}_ses-{ses_label}_desc-coverage_atlas.nii.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    apply_image_transform(template, atlas_t1, list(t1_to_mni), out, interpolation="genericLabel", threads=config.nthreads)
    img = nib.load(str(out))
    return np.rint(img.get_fdata()).astype(np.int32).squeeze(), img.affine


def write_parcel_crlb_figures(config, subject: str, session: str | None, atlas_t1: Path, parcel_qc_tsv: Path, t1_to_mni=None, mrsi_reference: Path | None = None) -> list[Path]:
    """One axial montage per metabolite: parcels green where mean CRLB is below
    the threshold (reliable), red where at or above it (unreliable).

    Replaces the previous nilearn glass brain, whose projection collapses the
    whole volume onto three planes -- so a deep unreliable parcel and a
    superficial one landed on top of each other and could not be told apart.
    Slices show where the unreliable parcels actually are.

    The template the run normalized into is drawn underneath, so the parcels
    can be read against anatomy rather than floating on black. The atlas is
    resampled into template space first (when a T1w->template transform is
    available); otherwise the figure is skipped rather than mis-aligned.
    """
    import nibabel as nib

    df = pd.read_csv(parcel_qc_tsv, sep="\t")
    if df.empty or "mean_crlb" not in df or "metabolite" not in df:
        return []
    if not t1_to_mni:
        return []

    atlas, affine = _resample_atlas_to_mni(config, subject, session, atlas_t1, t1_to_mni, mrsi_reference=mrsi_reference)

    underlay = None
    try:
        from mrsiprep.config.templates import template_t1w

        resolution = config.resolution_for("MNI152NLin2009cAsym", atlas_t1, mrsi_reference)
        template_img = nib.as_closest_canonical(template_t1w(resolution))
        candidate = np.squeeze(np.asarray(template_img.dataobj, dtype=float))
        # Only usable as an underlay if it is on the same grid as the atlas;
        # a mismatched template would misregister the overlay silently.
        if candidate.shape == atlas.shape:
            underlay = candidate
    except Exception:
        # The underlay is decoration: if the template cannot be fetched or
        # loaded for any reason, the quality overlay is still the point of the
        # figure, so draw it on black rather than failing the report.
        underlay = None

    indices = _axial_slice_indices(atlas)
    rows = []
    for metabolite, met_df in df.groupby("metabolite"):
        if not str(metabolite):
            continue
        # +1 reliable (green), -1 unreliable (red); parcels without a CRLB
        # estimate stay 0 and are masked out of the overlay.
        quality = {
            int(row.parcel_id): (1.0 if row.mean_crlb < CRLB_QUALITY_THRESHOLD else -1.0)
            for row in met_df.itertuples()
            if not (isinstance(row.mean_crlb, float) and np.isnan(row.mean_crlb))
        }
        if not quality:
            continue
        rows.append((str(metabolite), _value_volume(atlas, quality)))

    if not rows:
        return []
    out = coverage_figure_derivative(config.derivative_dir, subject, session, desc="parcelcrlbquality")
    # This function used to write one figure per metabolite. Those files are
    # this function's own output from an earlier version, and leaving them in
    # figures/ means the report embeds both generations, so clear them when
    # the grid that replaces them is written.
    for superseded in out.parent.glob("*_met-*_desc-parcelcrlbquality.png"):
        try:
            superseded.unlink()
        except OSError:
            # Best-effort cleanup: a file that cannot be removed (read-only
            # mount, concurrent run holding it) is not a reason to fail the
            # figure it is being replaced by. The narrowed glob in
            # _parcel_figures_html keeps a survivor out of the report anyway.
            continue
    return [
        _render_axial_grid(
            out,
            rows,
            indices,
            title=f"Parcelwise CRLB quality (green < {int(CRLB_QUALITY_THRESHOLD)}%, red \u2265)",
            cmap="RdYlGn",
            vmin=-1.0,
            vmax=1.0,
            underlay=underlay,
            # Green/red is a two-level categorical overlay, so it stays legible
            # through partial transparency, and the template underneath is what
            # lets the reader place an unreliable parcel anatomically.
            alpha=0.55,
        )
    ]


def write_parcel_qc_figures(
    config,
    subject: str,
    session: str | None,
    atlas_t1: Path | None,
    parcel_qc_tsv: Path | None,
    atlas_mrsi: Path | None = None,
    t1_to_mni=None,
    mrsi_reference: Path | None = None,
) -> list[Path]:
    """Generate both parcelwise figures; returns the list of written paths."""
    if atlas_t1 is None or parcel_qc_tsv is None or not Path(parcel_qc_tsv).exists():
        return []
    figures: list[Path] = []
    coverage = write_parcel_coverage_figure(config, subject, session, atlas_mrsi or atlas_t1, parcel_qc_tsv)
    if coverage is not None:
        figures.append(coverage)
    figures.extend(write_parcel_crlb_figures(config, subject, session, atlas_t1, parcel_qc_tsv, t1_to_mni=t1_to_mni, mrsi_reference=mrsi_reference))
    return figures

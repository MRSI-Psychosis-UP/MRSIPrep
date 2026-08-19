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
from mrsiprep.reports.slices import render_triplanar_png, triplanar_slices

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

    nonzero = coverage > 0.0
    if nonzero.any():
        center_ijk = tuple(int(round(coordinate)) for coordinate in np.argwhere(nonzero).mean(axis=0))
    else:
        center_ijk = None
    slices = triplanar_slices(coverage, center_ijk)
    masked = {plane: np.ma.masked_less_equal(data, 0.0) for plane, data in slices.items()}
    out = coverage_figure_derivative(config.derivative_dir, subject, session, desc="parcelcoverage")
    return render_triplanar_png(
        background_slices=masked,
        out_path=out,
        cmap="viridis",
        colorbar_label="MRSI anatomical coverage (%)",
        # Pin to the metric's real 0-100% range: coverage is often uniform
        # (e.g. exactly 100% everywhere), and matplotlib's default
        # autoscaling on a zero-variance field pads an arbitrary margin
        # around it (e.g. 90-110%) instead of showing the true, meaningful
        # scale, which reads as a bug ("over 100% coverage?") at a glance.
        vmin=0.0,
        vmax=100.0,
    )


def _resample_atlas_to_mni(config, subject: str, session: str | None, atlas_t1: Path, t1_to_mni, mrsi_reference: Path | None = None) -> tuple[np.ndarray, "object"]:
    """Resample the (subject-space) T1w atlas into MNI space via the same
    T1w->MNI transform used for MRSI outputs, so glass-brain projection (which
    assumes MNI space) is actually aligned with its silhouette."""
    import nibabel as nib
    from nilearn import datasets

    from mrsiprep.registration.transforms import apply_image_transform
    from mrsiprep.utils.images import resolve_mni_resolution

    resolution = resolve_mni_resolution(config.mni_resolution, atlas_t1, mrsi_reference)
    template = datasets.load_mni152_template(resolution)
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
    """One nilearn glass-brain per metabolite: parcels green where mean CRLB <
    threshold (reliable), red where >= threshold (unreliable).

    Glass-brain projection assumes MNI space, so the atlas is resampled into
    MNI space first (when a T1w->MNI transform is available); otherwise the
    figure is skipped rather than silently mis-aligned.
    """
    import matplotlib

    matplotlib.use("Agg")
    import nibabel as nib
    from nilearn import plotting

    df = pd.read_csv(parcel_qc_tsv, sep="\t")
    if df.empty or "mean_crlb" not in df or "metabolite" not in df:
        return []
    if not t1_to_mni:
        return []

    atlas, affine = _resample_atlas_to_mni(config, subject, session, atlas_t1, t1_to_mni, mrsi_reference=mrsi_reference)
    outputs: list[Path] = []
    for metabolite, met_df in df.groupby("metabolite"):
        if not str(metabolite):
            continue
        # +1 reliable (green), -1 unreliable (red); parcels without a CRLB estimate stay 0.
        quality = {
            int(row.parcel_id): (1.0 if row.mean_crlb < CRLB_QUALITY_THRESHOLD else -1.0)
            for row in met_df.itertuples()
            if not (isinstance(row.mean_crlb, float) and np.isnan(row.mean_crlb))
        }
        if not quality:
            continue
        volume = _value_volume(atlas, quality)
        img = nib.Nifti1Image(volume, affine)
        out = coverage_figure_derivative(config.derivative_dir, subject, session, desc="parcelcrlbquality", met=str(metabolite))
        out.parent.mkdir(parents=True, exist_ok=True)
        display = plotting.plot_glass_brain(
            img,
            cmap="RdYlGn",
            vmin=-1.0,
            vmax=1.0,
            plot_abs=False,
            threshold=0.5,
            colorbar=False,
            title=f"{metabolite}: CRLB quality (green<{int(CRLB_QUALITY_THRESHOLD)}%)",
        )
        display.savefig(str(out))
        display.close()
        outputs.append(out)
    return outputs


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

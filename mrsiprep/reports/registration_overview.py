"""MRSI-T1w-MNI registration alignment QC sections (T1w-space / MNI-space alignment tabs).

Each builder returns the alignment triplanar figure section; the caller
(:func:`mrsiprep.workflows.participant._step_reports`) appends that space's
signal-weighted leakage table (via :func:`leakage_table_html`, once leakage
QC has run -- a later pipeline step than registration/resampling) so the
picture and the number that quantifies it end up in the same tab.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from mrsiprep.io.naming import coverage_report_dir, qc_report_derivative
from mrsiprep.mrsi.resampling import resample_ref_met_to_t1w
from mrsiprep.reports.slices import load_canonical_data, render_triplanar_png, triplanar_slices
from mrsiprep.config.templates import template_head


def leakage_table_html(leakage_df: pd.DataFrame | None, space: str) -> str:
    if leakage_df is not None and not leakage_df.empty:
        space_df = leakage_df[leakage_df["space"] == space]
        if not space_df.empty:
            table = space_df.drop(columns=["space"]).to_html(index=False, border=0, float_format=lambda value: f"{value:.3f}")
            return f"<h3>Signal-weighted leakage</h3>{table}"
    if space == "T1w":
        # Leakage is computed only against maps that were actually resampled
        # into T1w space (transformed["T1w"]), which is opt-in via
        # --output-mrsi-t1w -- unlike the alignment figure above, which is
        # always rendered via a separate, cheap report-only resampling
        # (resample_ref_met_to_t1w). Without that flag there is simply no
        # T1w-space signal to measure leakage against, so make that explicit
        # rather than silently showing nothing next to the alignment image.
        return (
            "<h3>Signal-weighted leakage</h3>"
            "<p>Not computed: T1w-space leakage requires the full T1w-space resampled metabolite maps "
            "(<code>--output-mrsi-t1w</code>), which weren't requested for this run. The alignment image above "
            "uses a separate, lightweight report-only resampling and doesn't imply this data is available.</p>"
        )
    return ""


def build_t1w_alignment_sections(
    config,
    subject: str,
    session: str | None,
    raw_t1: Path,
    t1_ref_map_path: Path | None,
    orig_ref_map_path: Path | None = None,
    mrsi_to_t1_transforms: list[Path] | None = None,
) -> list[tuple[str, str]]:
    """Returns the T1w-space alignment tab's (heading, body_html) sections."""
    import numpy as np

    out = qc_report_derivative(config.derivative_dir, subject, session, "registration")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    if (t1_ref_map_path is None or not Path(t1_ref_map_path).exists()) and orig_ref_map_path is not None and mrsi_to_t1_transforms:
        # Minimal, report-only resampling: written under --work-dir rather than
        # the permanent BIDS derivatives (full T1w-space output is opt-in via
        # --output-mrsi-t1w).
        t1_ref_map_path = resample_ref_met_to_t1w(config, subject, session, orig_ref_map_path, mrsi_to_t1_transforms, raw_t1)

    if t1_ref_map_path is not None and Path(t1_ref_map_path).exists():
        t1_data = np.squeeze(load_canonical_data(raw_t1))
        ref_data = np.squeeze(load_canonical_data(t1_ref_map_path))
        t1_slices = triplanar_slices(t1_data)
        ref_slices = triplanar_slices(ref_data)
        t1_png = figures_dir / f"{out.stem}_space-T1w.png"
        render_triplanar_png(t1_slices, t1_png, overlay_slices=ref_slices, mode="alpha", colorbar_label=config.ref_met)
        body = f"<p>Reference metabolite map (<code>{config.ref_met}</code>) overlaid on raw T1w.</p><img src='figures/{t1_png.name}'>"
    else:
        body = "<p>No T1w-space reference metabolite map available.</p>"

    return [("T1w-space alignment", body)]


def build_mni_alignment_sections(
    config,
    subject: str,
    session: str | None,
    mni_ref_map_path: Path | None = None,
    mni_resolution: int | None = None,
) -> list[tuple[str, str]]:
    """Returns the MNI-space alignment tab's (heading, body_html) sections."""
    import nibabel as nib
    import numpy as np

    out = qc_report_derivative(config.derivative_dir, subject, session, "registration")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    if mni_ref_map_path is not None and Path(mni_ref_map_path).exists():
        template = _load_mni152_head_template(mni_resolution)
        template_data = np.squeeze(nib.as_closest_canonical(template).get_fdata())
        mni_data = np.squeeze(load_canonical_data(mni_ref_map_path))
        template_slices = triplanar_slices(template_data)
        mni_slices = triplanar_slices(mni_data)
        mni_png = figures_dir / f"{out.stem}_space-MNI.png"
        render_triplanar_png(
            template_slices,
            mni_png,
            overlay_slices=mni_slices,
            mode="solid",
            overlay_cmap="hot",
            colorbar_label=config.ref_met,
        )
        body = (
            f"<p>Reference metabolite map (<code>{config.ref_met}</code>) overlaid on the full-head MNI152 template, "
            f"opaque so placement inside the brain can be verified post-alignment.</p><img src='figures/{mni_png.name}'>"
        )
    else:
        body = "<p>MNI-space registration not available for this configuration.</p>"

    return [("MNI-space alignment", body)]


def _load_mni152_head_template(resolution: int | None):
    """Full-head (not skull-stripped) MNI152 T1 template, resampled to match
    the grid used by the run's reference template (see config/templates.py) so it aligns
    with MNI-space outputs produced by `transform_mrsi_maps()`.
    """
    import numpy as np
    from nilearn import image

    resolution = resolution or 1
    head = template_head()
    if resolution != 1:
        head = image.resample_img(head, np.eye(3) * resolution)
    return head

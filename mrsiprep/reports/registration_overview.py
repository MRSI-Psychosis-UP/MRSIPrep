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

from mrsiprep.io.naming import anat_derivative, coverage_report_dir, qc_report_derivative, resampling_work_path
from mrsiprep.mrsi.resampling import resample_ref_met_to_t1w
from mrsiprep.reports.slices import (
    load_canonical_data,
    load_canonical_data_with_affine,
    render_multi_slice_triplanar_svg_flicker,
    svg_object_html as _svg_object_html,
)
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
    out = qc_report_derivative(config.derivative_dir, subject, session, "registration")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    if (t1_ref_map_path is None or not Path(t1_ref_map_path).exists()) and orig_ref_map_path is not None and mrsi_to_t1_transforms:
        # Minimal, report-only resampling: written under --work-dir rather than
        # the permanent BIDS derivatives (full T1w-space output is opt-in via
        # --output-mrsi-t1w).
        t1_ref_map_path = resample_ref_met_to_t1w(config, subject, session, orig_ref_map_path, mrsi_to_t1_transforms, raw_t1)

    if t1_ref_map_path is not None and Path(t1_ref_map_path).exists():
        t1_data, t1_affine = load_canonical_data_with_affine(raw_t1)
        ref_data = load_canonical_data(t1_ref_map_path)
        wm_probseg_path = anat_derivative(config.derivative_dir, subject, session, space="T1w", label="WM", suffix_override="probseg")
        wm_mask = load_canonical_data(wm_probseg_path) if wm_probseg_path.exists() else None
        t1_svg = figures_dir / f"{out.stem}_space-T1w.svg"
        # Multiple slices per plane (not a single center slice), matching the
        # Template-space tab: a single slice can land on an unremarkable part
        # of the registration and miss a real misalignment a few slices away.
        render_multi_slice_triplanar_svg_flicker(
            t1_data.squeeze(),
            t1_svg,
            overlay=ref_data.squeeze(),
            flicker_id=out.stem,
            overlay_mode="solid",
            overlay_cmap="magma",
            colorbar_label=f"{config.ref_met} [IU]",
            affine=t1_affine,
            wm_mask=wm_mask,
        )
        body = (
            f"<p>Reference metabolite map (<code>{config.ref_met}</code>) overlaid on raw T1w"
            f"{', with the white-matter boundary in green' if wm_mask is not None else ''}. "
            f"Hover over the figure to flip between the two.</p>{_svg_object_html(t1_svg)}"
        )
    else:
        body = "<p>No T1w-space reference metabolite map available.</p>"

    return [("T1w-space alignment", body)]


def build_mni_alignment_sections(
    config,
    subject: str,
    session: str | None,
    mni_ref_map_path: Path | None = None,
    mni_resolution: int | None = None,
    t1_to_mni_transforms: list[Path] | None = None,
) -> list[tuple[str, str]]:
    """Returns the MNI-space alignment tab's (heading, body_html) sections.

    ``t1_to_mni_transforms``, when given along with a T1w-space WM probseg
    derivative, resamples the WM mask into MNI space (report-only, written
    under --work-dir -- same pattern as :func:`resample_ref_met_to_t1w`) so
    its contour can be drawn on the alignment figure too.
    """
    import nibabel as nib
    import numpy as np

    out = qc_report_derivative(config.derivative_dir, subject, session, "registration")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    if mni_ref_map_path is not None and Path(mni_ref_map_path).exists():
        template = nib.as_closest_canonical(_load_mni152_head_template(mni_resolution))
        # Name the template and its resolution explicitly: "MNI152" alone spans
        # several distinct templates, and the resolution decides what the
        # overlay can actually show.
        space_name = getattr(config, "output_spaces", None) or ["MNI152NLin2009cAsym"]
        template_label = (
            f"full-head <code>{space_name[0] if space_name else 'MNI152NLin2009cAsym'}</code> "
            f"template at {mni_resolution} mm"
        )
        template_data = np.squeeze(template.get_fdata())
        mni_data, _mni_affine = load_canonical_data_with_affine(mni_ref_map_path)
        mni_data = mni_data.squeeze()
        wm_mask = _resample_wm_mask_to_mni(config, subject, session, t1_to_mni_transforms, template)
        mni_svg = figures_dir / f"{out.stem}_space-MNI.svg"
        # Multiple slices per plane, not one: a single center slice can land
        # on an unremarkable part of the registration and miss a real
        # misalignment a few slices away. Coordinate titles/affine come from
        # the template (both layers share the same grid/resolution, so
        # either affine works; the template's is already loaded).
        render_multi_slice_triplanar_svg_flicker(
            template_data,
            mni_svg,
            overlay=mni_data,
            flicker_id=out.stem,
            overlay_mode="solid",
            overlay_cmap="magma",
            colorbar_label=f"{config.ref_met} [IU]",
            affine=template.affine,
            wm_mask=wm_mask,
        )
        body = (
            f"<p>Reference metabolite map (<code>{config.ref_met}</code>) overlaid on the "
            f"{template_label}{', with the white-matter boundary in green' if wm_mask is not None else ''}. "
            f"Hover over the figure to flip between the two.</p>{_svg_object_html(mni_svg)}"
        )
    else:
        body = "<p>MNI-space registration not available for this configuration.</p>"

    return [("Template-space alignment", body)]


def _resample_wm_mask_to_mni(config, subject: str, session: str | None, t1_to_mni_transforms: list[Path] | None, template):
    """Report-only resampling of the T1w-space WM probseg into MNI space, for
    the Template-space alignment figure's WM contour. Returns ``None`` (no
    contour drawn) when the transform or the WM probseg derivative isn't
    available -- the alignment image itself doesn't depend on it.
    """
    if not t1_to_mni_transforms:
        return None
    wm_probseg_path = anat_derivative(config.derivative_dir, subject, session, space="T1w", label="WM", suffix_override="probseg")
    if not wm_probseg_path.exists():
        return None
    from mrsiprep.registration.transforms import apply_image_transform

    out = resampling_work_path(config.work_dir, subject, session, space="MNI152NLin2009cAsym", label="WM", desc="probseg")
    if not out.exists() or config.overwrite_transform or config.overwrite:
        apply_image_transform(template, wm_probseg_path, t1_to_mni_transforms, out, interpolation="linear", threads=config.nthreads)
    return load_canonical_data(out)


def _load_mni152_head_template(resolution: int | None):
    """Full-head (not skull-stripped) MNI152 T1 template, resampled to match
    the grid used by the run's reference template (see config/templates.py) so it aligns
    with MNI-space outputs produced by `transform_mrsi_maps()`.
    """
    import nibabel as nib
    import numpy as np
    from nilearn import image

    resolution = resolution or 1
    head = template_head()
    if resolution != 1:
        # Cast to float32 before resampling: the fetched template is int16,
        # and resample_img's own implicit int->float cast during
        # interpolation raises a UserWarning on every call otherwise.
        head = nib.Nifti1Image(np.asarray(head.dataobj, dtype=np.float32), head.affine, head.header)
        head = image.resample_img(head, np.eye(3) * resolution)
    return head

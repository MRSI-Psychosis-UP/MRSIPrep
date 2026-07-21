"""MRSI-T1w-MNI registration alignment QC report."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.naming import qc_report_derivative
from mrsiprep.mrsi.resampling import resample_ref_met_to_t1w
from mrsiprep.reports.slices import html_page, load_canonical_data, render_triplanar_png, triplanar_slices


def write_registration_overview_report(
    config,
    subject: str,
    session: str | None,
    raw_t1: Path,
    t1_ref_map_path: Path | None,
    mni_ref_map_path: Path | None = None,
    mni_resolution: int | None = None,
    orig_ref_map_path: Path | None = None,
    mrsi_to_t1_transforms: list[Path] | None = None,
) -> Path:
    import nibabel as nib
    import numpy as np

    out = qc_report_derivative(config.derivative_dir, subject, session, "registration")
    out.parent.mkdir(parents=True, exist_ok=True)
    figures_dir = out.parent / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    sections: list[tuple[str, str]] = []

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
        sections.append(("T1w-space alignment", f"<p>Reference metabolite map (<code>{config.ref_met}</code>) overlaid on raw T1w.</p><img src='figures/{t1_png.name}'>"))
    else:
        sections.append(("T1w-space alignment", "<p>No T1w-space reference metabolite map available.</p>"))

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
        sections.append(("MNI-space alignment", f"<p>Reference metabolite map (<code>{config.ref_met}</code>) overlaid on the full-head MNI152 template, opaque so placement inside the brain can be verified post-alignment.</p><img src='figures/{mni_png.name}'>"))
    else:
        sections.append(("MNI-space alignment", "<p>MNI-space registration not available for this configuration.</p>"))

    out.write_text(html_page(f"Registration QC: sub-{subject}" + (f" ses-{session}" if session else ""), sections), encoding="utf-8")
    return out


def _load_mni152_head_template(resolution: int | None):
    """Full-head (not skull-stripped) MNI152 T1 template, resampled to match
    the grid used by `nilearn.datasets.load_mni152_template()` so it aligns
    with MNI-space outputs produced by `transform_mrsi_maps()`.
    """
    import numpy as np
    from nilearn import datasets, image

    resolution = resolution or 1
    head = image.load_img(datasets.fetch_icbm152_2009(verbose=0)["t1"])
    if resolution != 1:
        head = image.resample_img(head, np.eye(3) * resolution)
    return head

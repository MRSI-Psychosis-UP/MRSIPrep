"""Resampled per-metabolite maps (MRSI Space-T1 / MRSI Space-Template tabs).

The alignment tabs' main figure (:func:`mrsiprep.reports.slices.render_multi_slice_triplanar_svg_flicker`)
only shows the reference metabolite (``config.ref_met``), since that is the
map used to drive the MRSI<->T1w/MNI registration itself. The other
metabolites were resampled with the same transform
(:func:`mrsiprep.mrsi.resampling.transform_mrsi_maps` always resamples every
metabolite, not just the reference), so this module renders one
equally-spaced axial montage per metabolite in each output space, in their
own tabs -- same presentation as the MRSI Raw/PVC tabs
(:mod:`mrsiprep.reports.mrsi_raw_overview`,
:mod:`mrsiprep.reports.mrsi_pvc_overview`) -- so every metabolite's alignment
can be spot-checked, not just the reference's.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mrsiprep.io.naming import coverage_report_dir, qc_report_derivative
from mrsiprep.reports.slices import load_canonical_data, load_canonical_data_with_affine, render_axial_overlay_montage

_CMAP = "magma"


def build_alignment_metabolite_sections(
    config,
    subject: str,
    session: str | None,
    space: str,
    background: np.ndarray,
    resampled_maps: dict[str, Path],
    background_label: str = "the anatomy",
) -> list[tuple[str, str]]:
    """Returns an intro section plus one (heading, body_html) section per
    metabolite: an axial montage of that metabolite's ``space``-space map
    overlaid on ``background`` (the same anatomy the alignment figure uses).

    ``resampled_maps`` is the ``space`` entry of :func:`transform_mrsi_maps`'s
    output (e.g. ``transformed.get("T1w", {})``) -- besides every metabolite,
    it also carries quality-map entries under other key patterns
    (``crlb-*``, ``snr``, ``fwhm``, ``spikemask-*``), so this restricts to
    keys in ``config.metabolites`` rather than every key present. Metabolites
    whose resampled map doesn't exist (not requested, or resampling failed)
    are skipped rather than shown blank.
    """
    out = qc_report_derivative(config.derivative_dir, subject, session, "registration")
    figures_dir = coverage_report_dir(config.derivative_dir, subject, session) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    metabolites = sorted(met for met in (config.metabolites or []) if met in (resampled_maps or {}))
    if not metabolites:
        return []

    sections: list[tuple[str, str]] = [(
        "Per-metabolite maps",
        f"<p>Each metabolite's map resampled into {space} space, overlaid on {background_label}, at "
        "equally-spaced axial slices.</p>",
    )]
    for met in metabolites:
        met_path = resampled_maps.get(met)
        if met_path is None or not Path(met_path).exists():
            continue
        overlay = load_canonical_data(met_path)
        montage_png = figures_dir / f"{out.stem}_space-{space}_met-{met}_align-slices.png"
        render_axial_overlay_montage(background, overlay, montage_png, label=met, overlay_cmap=_CMAP)
        sections.append((f"Metabolite: {met}", f"<img src='figures/{montage_png.name}'>"))

    return sections


def build_mrsi_t1w_sections(
    config,
    subject: str,
    session: str | None,
    raw_t1: Path,
    t1_maps: dict[str, Path] | None,
) -> list[tuple[str, str]] | None:
    """MRSI Space-T1 tab: every metabolite's T1w-space map over the raw T1w.

    Returns ``None`` (tab omitted, like MRSI PVC under ``--no-pvc``) when no
    T1w-space maps were produced -- full T1w-space resampling is opt-in via
    ``--output-mrsi-t1w``.
    """
    if not t1_maps:
        return None
    background, _affine = load_canonical_data_with_affine(raw_t1)
    return build_alignment_metabolite_sections(
        config, subject, session, "T1w", background, t1_maps, background_label="the raw T1w"
    ) or None


def build_mrsi_template_sections(
    config,
    subject: str,
    session: str | None,
    mni_resolution: int | None,
    mni_maps: dict[str, Path] | None,
) -> list[tuple[str, str]] | None:
    """MRSI Space-Template tab: every metabolite's MNI-space map over the
    full-head template, at the run's MNI resolution. ``None`` (tab omitted)
    when no MNI-space maps were produced."""
    if not mni_maps:
        return None
    import nibabel as nib

    # Imported at call time: registration_overview is the module tests patch
    # _load_mni152_head_template on.
    from mrsiprep.reports import registration_overview

    template = nib.as_closest_canonical(registration_overview._load_mni152_head_template(mni_resolution))
    background = np.squeeze(template.get_fdata())
    return build_alignment_metabolite_sections(
        config, subject, session, "MNI152NLin2009cAsym", background, mni_maps,
        background_label=f"the full-head template at {mni_resolution or 1} mm",
    ) or None

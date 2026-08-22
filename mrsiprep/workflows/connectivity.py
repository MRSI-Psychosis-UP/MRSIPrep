"""Metabolic profile and connectivity workflow."""

from __future__ import annotations

from mrsiprep.connectivity.export import export_connectivity, export_metabolic_profiles


def run_connectivity_workflow(config, subject, session, regional_table, parcels, metabolite_maps, crlb_maps, brainmask, gm_fraction_path=None):
    """Estimate perturbation-augmented regional metabolic profiles, then
    optionally correlate them into a metabolic connectivity matrix.

    Profile estimation (CRLB-scaled Monte Carlo uncertainty propagation,
    Instrella & Juchem 2024) always runs, for every recording, independent of
    ``--parcellation-mode`` or ``--write-connectivity``. Connectivity-matrix
    construction is the optional add-on: it reuses the already-computed profiles rather than
    recomputing them, and only runs when ``config.write_connectivity`` is
    set.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param regional_table: Path to the per-parcel regional metabolite TSV,
        as produced by :func:`mrsiprep.parcellation.extraction.extract_regional_metabolites`.
    :param parcels: Backend-specific parcellation result (supplies
        ``atlas_name``, ``atlas_mrsi``, and ``scale``).
    :param metabolite_maps: MRSI-space metabolite maps used to compute
        perturbation-based profiles.
    :param crlb_maps: Matching per-metabolite CRLB maps.
    :param brainmask: MRSI-space brainmask restricting which voxels
        contribute to the profiles.
    :param gm_fraction_path: Optional gray-matter fraction map, used to
        weight profiles by GM content when given.
    :returns: Dict with a ``"profiles"`` entry (path to the exported
        metabolic-profile ``.npz``, always present) plus ``"matrix_npz"``,
        ``"nodes"``, and ``"edges"`` entries when ``--write-connectivity``
        was also set.
    """
    scale = _scale_token(parcels)
    profiles, profile_npz, table = export_metabolic_profiles(
        config,
        subject,
        session,
        regional_table,
        parcels.atlas_name,
        metabolite_maps,
        crlb_maps,
        brainmask,
        parcels.atlas_mrsi,
        gm_fraction_path=gm_fraction_path,
        scale=scale,
    )
    outputs = {"profiles": profile_npz}
    if config.write_connectivity:
        outputs.update(export_connectivity(config, subject, session, profiles, table, parcels.atlas_name, scale=scale))
    return outputs


def _scale_token(parcels) -> str | None:
    """Scale entity for this parcellation's connectivity outputs.

    Folds the gyral-WM growth in when several were requested (mirroring
    Chimera's own ``scale3grow2mm`` desc convention), so grow variants of the
    same scheme/scale don't overwrite each other. Single-grow runs are
    unaffected and keep their existing filenames.
    """
    if getattr(parcels, "grow", None) is None:
        return parcels.scale
    return f"{parcels.scale or ''}grow{parcels.grow}mm"

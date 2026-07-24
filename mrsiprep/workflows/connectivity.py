"""Connectivity workflow."""

from __future__ import annotations

from mrsiprep.connectivity.export import export_connectivity


def run_connectivity_workflow(config, subject, session, regional_table, parcels, metabolite_maps, crlb_maps, brainmask, gm_fraction_path=None):
    """Build and export perturbation-based metabolic connectivity matrices.

    A no-op returning ``{}`` unless ``--write-connectivity`` is set.
    Delegates to :func:`mrsiprep.connectivity.export.export_connectivity`.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param regional_table: Path to the per-parcel regional metabolite TSV,
        as produced by :func:`mrsiprep.parcellation.extraction.extract_regional_metabolites`.
    :param parcels: Backend-specific parcellation result (supplies
        ``atlas_name``, ``atlas_mrsi``, and ``scale``).
    :param metabolite_maps: MRSI-space metabolite maps used to compute
        perturbation-based edges.
    :param crlb_maps: Matching per-metabolite CRLB maps.
    :param brainmask: MRSI-space brainmask restricting which voxels
        contribute to connectivity edges.
    :param gm_fraction_path: Optional gray-matter fraction map, used to
        weight edges by GM content when given.
    :returns: Dict of exported connectivity matrix paths, or ``{}`` if
        ``config.write_connectivity`` is false.
    """
    if not config.write_connectivity:
        return {}
    return export_connectivity(
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
        scale=parcels.scale,
    )

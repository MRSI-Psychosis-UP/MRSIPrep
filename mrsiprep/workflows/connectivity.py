"""Connectivity workflow."""

from __future__ import annotations

from mrsiprep.connectivity.export import export_connectivity


def run_connectivity_workflow(config, subject, session, regional_table, parcels, metabolite_maps, crlb_maps, brainmask, gm_fraction_path=None):
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

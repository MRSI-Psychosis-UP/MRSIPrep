"""Connectivity export helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from mrsiprep.connectivity.connectivity import compute_metabolic_profiles, correlate_metabolic_profiles
from mrsiprep.connectivity.edges import build_edges
from mrsiprep.connectivity.nodes import build_nodes
from mrsiprep.io.naming import subject_session_dir


def _processing_label(config, gm_weighted: bool) -> str:
    processing = []
    if config.filter_biharmonic:
        processing.append("filt-biharmonic")
    if not config.no_pvc:
        processing.append("pvcorr_GM" if gm_weighted else "pvcorr")
    return ("_" + "_".join(processing)) if processing else ""


def _scale_entity(scale: str | None) -> str:
    scale_value = str(scale)[len("scale"):] if scale and str(scale).lower().startswith("scale") else scale
    return f"_scale{scale_value}" if scale_value else ""


def _metabolic_profile_path(config, subject: str, session: str | None, atlas_name: str, scale: str | None, gm_weighted: bool, n_perturbations: int) -> Path:
    out_dir = subject_session_dir(config.derivative_dir, subject, session, "connectivity")
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"sub-{subject}" + (f"_ses-{session}" if session else "")
    processing_label = _processing_label(config, gm_weighted)
    return out_dir / f"{prefix}_atlas-{atlas_name}{_scale_entity(scale)}_npert-{n_perturbations}{processing_label}_desc-metabolicprofiles_mrsi.npz"


def _connectivity_matrix_path(config, subject: str, session: str | None, atlas_name: str, scale: str | None, gm_weighted: bool, n_perturbations: int) -> Path:
    out_dir = subject_session_dir(config.derivative_dir, subject, session, "connectivity")
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"sub-{subject}" + (f"_ses-{session}" if session else "")
    processing_label = _processing_label(config, gm_weighted)
    return out_dir / f"{prefix}_atlas-{atlas_name}{_scale_entity(scale)}_npert-{n_perturbations}{processing_label}_desc-connectivity_mrsi.npz"


def _filter_excluded_parcels(table: pd.DataFrame, exclude_patterns: str | None, max_parcel_id: int | None) -> pd.DataFrame:
    if exclude_patterns:
        patterns = [pattern.strip() for pattern in exclude_patterns.split(",") if pattern.strip()]
        if patterns:
            names = table["parcel_name"].astype(str)
            mask = pd.Series(False, index=table.index)
            for pattern in patterns:
                mask |= names.str.contains(pattern, regex=False)
            table = table[~mask]
    if max_parcel_id is not None:
        table = table[table["parcel_id"] < max_parcel_id]
    return table


def export_metabolic_profiles(
    config,
    subject: str,
    session: str | None,
    regional_table: Path,
    atlas_name: str,
    metabolite_maps: dict[str, Path],
    crlb_maps: dict[str, Path],
    brainmask: Path,
    atlas_mrsi: Path,
    gm_fraction_path: Path | None = None,
    scale: str | None = None,
):
    """Perturbation-augmented regional metabolic profiles (uncertainty
    propagation via ``--connectivity-n-perturbations`` CRLB-scaled draws per
    metabolite). Runs unconditionally for every recording, independently of
    ``--write-connectivity`` -- the profile is the shared representation any
    downstream analysis (including, optionally, connectivity) builds on.

    Returns ``(MetabolicProfileResult, profile_npz_path)``.
    """
    table = _filter_excluded_parcels(pd.read_csv(regional_table, sep="\t"), config.connectivity_exclude_parcels, config.connectivity_max_parcel_id)
    parcel_ids = sorted(table["parcel_id"].unique().tolist())
    profiles = compute_metabolic_profiles(
        metabolite_maps,
        crlb_maps,
        brainmask,
        atlas_mrsi,
        parcel_ids,
        n_perturbations=config.connectivity_n_perturbations,
        sigma_scale=config.connectivity_sigma_scale,
        nthreads=config.nthreads,
        gm_fraction_path=gm_fraction_path,
    )
    name_by_id = table.drop_duplicates("parcel_id").set_index("parcel_id")["parcel_name"]
    parcel_names = np.array([str(name_by_id.get(parcel_id, parcel_id)) for parcel_id in profiles.parcel_ids])
    profile_npz = _metabolic_profile_path(config, subject, session, atlas_name, scale, profiles.gm_weighted, profiles.n_perturbations)
    np.savez(
        profile_npz,
        features=profiles.features,
        parcel_concentrations=profiles.parcel_concentrations,
        labels_indices=profiles.parcel_ids,
        parcel_names=parcel_names,
        metabolites=np.array(profiles.metabolites),
        npert=profiles.n_perturbations,
        sigma_scale=profiles.sigma_scale,
        gm_weighted=profiles.gm_weighted,
    )
    return profiles, profile_npz, table


def export_connectivity(
    config,
    subject: str,
    session: str | None,
    profiles,
    table: pd.DataFrame,
    atlas_name: str,
    scale: str | None = None,
) -> dict[str, Path]:
    """Metabolic similarity matrix built from an already-computed
    :class:`~mrsiprep.connectivity.connectivity.MetabolicProfileResult`
    (see :func:`export_metabolic_profiles`). Optional add-on, gated on
    ``--write-connectivity``."""
    result = correlate_metabolic_profiles(profiles, method=config.connectivity_method)
    sim = result.similarity
    name_by_id = table.drop_duplicates("parcel_id").set_index("parcel_id")["parcel_name"]
    parcel_names = np.array([str(name_by_id.get(parcel_id, parcel_id)) for parcel_id in result.parcel_ids])
    matrix_npz = _connectivity_matrix_path(config, subject, session, atlas_name, scale, result.gm_weighted, result.n_perturbations)
    nodes_tsv = matrix_npz.with_name(matrix_npz.stem.replace("desc-connectivity", "desc-nodes") + ".tsv")
    edges_tsv = matrix_npz.with_name(matrix_npz.stem.replace("desc-connectivity", "desc-edges") + ".tsv")
    matrix_tsv = matrix_npz.with_suffix(".tsv")
    np.savez(
        matrix_npz,
        matrix=sim.to_numpy(),
        parcel_concentrations=result.parcel_concentrations,
        labels_indices=result.parcel_ids,
        parcel_names=parcel_names,
        metabolites=np.array(result.metabolites),
        method=result.method,
        npert=result.n_perturbations,
        sigma_scale=result.sigma_scale,
        gm_weighted=result.gm_weighted,
    )
    sim_labeled = sim.copy()
    sim_labeled.index = parcel_names
    sim_labeled.columns = parcel_names
    sim_labeled.to_csv(matrix_tsv, sep="\t")
    build_nodes(table).to_csv(nodes_tsv, sep="\t", index=False)
    build_edges(sim, config.connectivity_method).to_csv(edges_tsv, sep="\t", index=False)
    return {"matrix_npz": matrix_npz, "matrix_tsv": matrix_tsv, "nodes": nodes_tsv, "edges": edges_tsv}

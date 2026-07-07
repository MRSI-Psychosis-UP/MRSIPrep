"""Legacy-compatible parcelwise metabolite profile export."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

from mrsiprep.io.naming import mrsi_parcel_dir
from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.utils.images import load_3d_data
from mrsiprep.utils.tables import read_labels


def export_metprofile_npz(
    config,
    subject: str,
    session: str | None,
    metabolite_maps: dict[str, Path],
    water_map: Path | None,
    parcels: ParcellationResult,
    regional_table: Path,
    t1mask_path: Path | None,
) -> Path:
    labels = read_labels(parcels.labels).sort_values("parcel_id").reset_index(drop=True)
    regional = pd.read_csv(regional_table, sep="\t")
    metabolites = list(metabolite_maps)
    value_column = config.regional_summary if config.regional_summary in {"mean", "median", "weighted_mean"} else "mean"
    atlas = np.rint(nib.load(str(parcels.atlas_mrsi)).get_fdata(dtype=np.float32).squeeze()).astype(np.int32)

    parcel_ids = labels["parcel_id"].astype(int).to_numpy()
    parcel_names = labels["parcel_name"].astype(str).to_numpy(dtype=object)
    voxel_counts = np.asarray([np.count_nonzero(atlas == parcel_id) for parcel_id in parcel_ids], dtype=np.int64)
    profiles = np.full((len(parcel_ids), len(metabolites)), np.nan, dtype=np.float64)
    for met_index, metabolite in enumerate(metabolites):
        subset = regional[regional["metabolite"] == metabolite].set_index("parcel_id")
        for parcel_index, parcel_id in enumerate(parcel_ids):
            if parcel_id in subset.index:
                profiles[parcel_index, met_index] = float(subset.loc[parcel_id, value_column])

    water_signal = np.full(len(parcel_ids), np.nan, dtype=np.float64)
    if water_map is not None and Path(water_map).exists():
        water = load_3d_data(water_map, dtype=np.float32, label="water signal map")[1]
        for parcel_index, parcel_id in enumerate(parcel_ids):
            mask = (atlas == parcel_id) & np.isfinite(water)
            if np.any(mask):
                water_signal[parcel_index] = float(np.nanmean(water[mask]))

    retained = (voxel_counts > 0) & np.any(np.isfinite(profiles), axis=1)
    ignored = ~retained
    processing_label = "raw" if config.no_pvc else "pvcorr_GM"
    desc_entity = "metprofiles" if config.no_pvc else "GMmetprofiles"
    atlas_entity = parcels.atlas_name
    if parcels.mode == "chimera" and not atlas_entity.lower().startswith("chimera"):
        atlas_entity = f"chimera{atlas_entity}"
    scale_entity = f"_scale{parcels.scale}" if parcels.scale else ""
    prefix = f"sub-{subject}" + (f"_ses-{session}" if session else "")
    out_dir = mrsi_parcel_dir(config.derivative_dir, subject, session)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{prefix}_atlas-{atlas_entity}{scale_entity}_desc-{desc_entity}_mrsi.npz"

    metadata = {
        "sub": subject,
        "ses": session,
        "mode": config.processing_mode,
        "parcellation_mode": parcels.mode,
        "regional_summary": value_column,
    }
    np.savez_compressed(
        out,
        metab_profiles=profiles[retained],
        water_signal=water_signal[retained],
        metabolites=np.asarray(metabolites, dtype=object),
        parcel_labels=parcel_ids[retained],
        parcel_names=parcel_names[retained],
        parcel_voxel_counts=voxel_counts[retained],
        parcel_labels_ignore=parcel_names[ignored],
        parcel_label_ids_ignore=parcel_ids[ignored],
        metabolite_image_paths=np.asarray([str(metabolite_maps[met]) for met in metabolites], dtype=object),
        water_signal_path=str(water_map) if water_map else "",
        parcellation_path=str(parcels.atlas_mrsi),
        t1mask_path=str(t1mask_path) if t1mask_path else "",
        profile_source="preproc",
        preproc_option=processing_label,
        mrsi_space="orig",
        mrsi_res="",
        group=config.bids_dir.name,
        subject_id=subject,
        session_id=session or "",
        parc_scheme=parcels.atlas_name,
        scale=int(parcels.scale) if parcels.scale and str(parcels.scale).isdigit() else parcels.scale or "",
        grow=config.chimera_grow if parcels.mode == "chimera" else 0,
        metadata=np.asarray([metadata], dtype=object),
    )
    return out

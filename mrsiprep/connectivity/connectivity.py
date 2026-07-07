"""Perturbation-based metabolite connectivity.

Builds a per-parcel feature vector from many CRLB-scaled noise perturbations of
each metabolite map (z-scored per metabolite before parcel averaging, so no single
metabolite's scale dominates the correlation), then correlates parcels over that
vector. This mirrors the statistical approach used in the mrsitoolbox MetSiM
pipeline (``Randomize.perturbate`` + ``MeSiM.parcellate_vectorized``), but is a
from-scratch, vectorized implementation rather than a port of that code.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from scipy.spatial.distance import pdist, squareform

from mrsiprep.utils.images import load_3d_data


def perturb_metabolite_map(
    signal: np.ndarray,
    crlb: np.ndarray,
    brainmask: np.ndarray,
    sigma_scale: float = 2.0,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    rng = rng or np.random.default_rng()
    sigma = signal * crlb / 100
    scale = np.clip(np.nan_to_num(sigma * sigma_scale, nan=0.0), 0, None)
    upper = signal.mean() + 3 * signal.std()
    noisy = rng.normal(signal, scale)
    noisy = np.clip(noisy, 0, upper)
    noisy[brainmask == 0] = 0
    return noisy


def build_parcel_indexer(atlas_3d: np.ndarray, parcel_ids: np.ndarray) -> np.ndarray:
    """Map each voxel to a 0-based row index into ``parcel_ids`` (or -1 if the
    voxel's label isn't in ``parcel_ids``), so per-parcel reductions for every
    metabolite/perturbation can share one ``np.bincount`` call per array instead
    of one ``scipy.ndimage`` pass per metabolite per parcel.
    """
    lookup = np.full(int(atlas_3d.max()) + 1, -1, dtype=np.int64)
    lookup[parcel_ids] = np.arange(len(parcel_ids))
    flat = atlas_3d.reshape(-1)
    safe = np.clip(flat, 0, lookup.size - 1)
    return np.where(flat == safe, lookup[safe], -1)


def parcellate_means(
    image_4d: np.ndarray,
    atlas_3d: np.ndarray,
    parcel_ids: np.ndarray,
    parcel_index: np.ndarray | None = None,
    voxel_weights: np.ndarray | None = None,
) -> np.ndarray:
    """Per-metabolite, per-parcel mean that skips NaN voxels (matching the
    reference implementation's ``np.nanmean`` over a boolean mask), computed for
    all metabolites in one vectorized pass via ``np.bincount`` rather than one
    ``scipy.ndimage`` label-reduction pass per metabolite.

    If ``voxel_weights`` is given (e.g. a GM partial-volume fraction map), the
    per-parcel value is a weighted mean instead of a plain mean — voxels with
    low GM fraction (partial WM/CSF contamination at the parcel boundary)
    contribute proportionally less, since chimera cortical parcels are GM
    structures and connectivity should reflect GM signal specifically.
    """
    n_metabolites = image_4d.shape[0]
    n_parcels = len(parcel_ids)
    parcel_index = build_parcel_indexer(atlas_3d, parcel_ids) if parcel_index is None else parcel_index
    in_parcel = parcel_index >= 0
    safe_index = np.where(in_parcel, parcel_index, 0)

    flat = image_4d.reshape(n_metabolites, -1)
    weights_flat = np.ones(flat.shape[1]) if voxel_weights is None else np.nan_to_num(voxel_weights.reshape(-1), nan=0.0)
    valid = in_parcel[None, :] & ~np.isnan(flat)
    weighted_valid = valid * weights_flat[None, :]
    filled = np.where(valid, flat, 0.0) * weights_flat[None, :]

    out = np.empty((n_metabolites, n_parcels), dtype=np.float64)
    for met_idx in range(n_metabolites):
        sums = np.bincount(safe_index, weights=filled[met_idx], minlength=n_parcels)[:n_parcels]
        counts = np.bincount(safe_index, weights=weighted_valid[met_idx], minlength=n_parcels)[:n_parcels]
        with np.errstate(invalid="ignore", divide="ignore"):
            out[met_idx] = np.where(counts > 0, sums / counts, np.nan)
    return out


def parcellate_zscored(
    perturbed_4d: np.ndarray,
    atlas_3d: np.ndarray,
    parcel_ids: np.ndarray,
    parcel_index: np.ndarray | None = None,
    voxel_weights: np.ndarray | None = None,
) -> np.ndarray:
    means = perturbed_4d.mean(axis=(1, 2, 3), keepdims=True)
    stds = perturbed_4d.std(axis=(1, 2, 3), keepdims=True)
    stds = np.where(stds == 0, 1, stds)
    zscored = (perturbed_4d - means) / stds
    return parcellate_means(zscored, atlas_3d, parcel_ids, parcel_index=parcel_index, voxel_weights=voxel_weights)


def _sample_one(
    signals: np.ndarray,
    crlbs: np.ndarray,
    brainmask: np.ndarray,
    atlas: np.ndarray,
    parcel_ids: np.ndarray,
    parcel_index: np.ndarray,
    sigma_scale: float,
    seed: int,
    voxel_weights: np.ndarray | None = None,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    perturbed = np.stack([perturb_metabolite_map(signals[idx], crlbs[idx], brainmask, sigma_scale, rng) for idx in range(signals.shape[0])])
    return parcellate_zscored(perturbed, atlas, parcel_ids, parcel_index=parcel_index, voxel_weights=voxel_weights)


def _rank_rows(features: np.ndarray) -> np.ndarray:
    """Vectorized row-wise ranking via double argsort, replacing a per-row
    ``scipy.stats.rankdata`` Python loop. Perturbation-averaged floating-point
    parcel means essentially never tie exactly, so plain (non-tie-averaged)
    ranks are used; this matches ``rankdata``'s output for the tie-free case
    that occurs in practice here.
    """
    order = np.argsort(features, axis=1, kind="mergesort")
    ranks = np.empty_like(order, dtype=np.float64)
    row_index = np.arange(features.shape[0])[:, None]
    ranks[row_index, order] = np.arange(1, features.shape[1] + 1)
    return ranks


def _correlate(features: np.ndarray, method: str) -> np.ndarray:
    if method == "pearson":
        return np.corrcoef(features)
    if method == "spearman":
        ranked = _rank_rows(features)
        return np.corrcoef(ranked)
    if method == "cosine":
        norms = np.linalg.norm(features, axis=1, keepdims=True)
        normed = np.divide(features, norms, out=np.zeros_like(features), where=norms > 0)
        return normed @ normed.T
    if method == "euclidean_distance":
        return squareform(pdist(np.nan_to_num(features), metric="euclidean"))
    raise ValueError(f"Unsupported connectivity method: {method}")


@dataclass
class ConnectivityResult:
    similarity: pd.DataFrame
    parcel_concentrations: np.ndarray  # shape (n_metabolites, n_parcels), raw (un-zscored) parcel means
    metabolites: list[str]
    parcel_ids: np.ndarray
    method: str
    n_perturbations: int
    sigma_scale: float
    gm_weighted: bool


def compute_metabolite_connectivity(
    metabolite_maps: dict[str, Path],
    crlb_maps: dict[str, Path],
    brainmask_path: Path,
    atlas_path: Path,
    parcel_ids: list[int],
    method: str = "spearman",
    n_perturbations: int = 50,
    sigma_scale: float = 2.0,
    nthreads: int = 1,
    seed: int | None = None,
    gm_fraction_path: Path | None = None,
) -> ConnectivityResult:
    metabolites = [met for met in metabolite_maps if met in crlb_maps]
    if not metabolites:
        raise ValueError("No metabolites with both signal and CRLB maps available for connectivity computation.")

    signals = np.stack([load_3d_data(metabolite_maps[met], label=f"{met} map")[1] for met in metabolites])
    crlbs = np.stack([load_3d_data(crlb_maps[met], label=f"{met} CRLB map")[1] for met in metabolites])
    brainmask = load_3d_data(brainmask_path, label="brainmask")[1]
    atlas = load_3d_data(atlas_path, label="MRSI atlas")[1].astype(int)
    parcel_ids_arr = np.asarray(parcel_ids, dtype=int)
    parcel_index = build_parcel_indexer(atlas, parcel_ids_arr)
    gm_fraction = load_3d_data(gm_fraction_path, label="GM partial volume fraction")[1] if gm_fraction_path is not None and Path(gm_fraction_path).exists() else None

    seed = seed if seed is not None else np.random.SeedSequence().entropy
    seeds = [int(seed) + index for index in range(n_perturbations)]

    progress_columns = (TextColumn("[progress.description]{task.description}"), BarColumn(), MofNCompleteColumn(), TimeElapsedColumn())
    with Progress(*progress_columns, transient=True) as progress:
        task = progress.add_task("Regional metabolite extraction (perturbations)", total=n_perturbations)
        if nthreads <= 1:
            samples = []
            for task_seed in seeds:
                samples.append(_sample_one(signals, crlbs, brainmask, atlas, parcel_ids_arr, parcel_index, sigma_scale, task_seed, voxel_weights=gm_fraction))
                progress.advance(task)
        else:
            samples = [None] * len(seeds)
            with ThreadPoolExecutor(max_workers=nthreads) as executor:
                futures = {
                    executor.submit(_sample_one, signals, crlbs, brainmask, atlas, parcel_ids_arr, parcel_index, sigma_scale, task_seed, voxel_weights=gm_fraction): index
                    for index, task_seed in enumerate(seeds)
                }
                for future in as_completed(futures):
                    samples[futures[future]] = future.result()
                    progress.advance(task)

    # shape (n_perturbations, n_metabolites, n_parcels) -> (n_parcels, n_metabolites * n_perturbations)
    stacked = np.stack(samples)
    features = stacked.transpose(2, 1, 0).reshape(len(parcel_ids_arr), -1)

    matrix = _correlate(features, method)
    similarity = pd.DataFrame(matrix, index=parcel_ids_arr, columns=parcel_ids_arr)
    parcel_concentrations = parcellate_means(signals, atlas, parcel_ids_arr, parcel_index=parcel_index, voxel_weights=gm_fraction)
    return ConnectivityResult(
        similarity=similarity,
        parcel_concentrations=parcel_concentrations,
        metabolites=metabolites,
        parcel_ids=parcel_ids_arr,
        method=method,
        n_perturbations=n_perturbations,
        sigma_scale=sigma_scale,
        gm_weighted=gm_fraction is not None,
    )

"""MIDAS-style fuzzy c-means tissue segmentation.

Replicates the tissue-segmentation approach of Maudsley et al. 2006
("Comprehensive processing, display and analysis for in vivo MR spectroscopic
imaging", NMR Biomed 19:492-503), which applies a fuzzy c-means clustering
algorithm (their ref. 24, Cheng/Goldof/Hall) to classify voxels into more
groups than tissue classes, then merges them into GM/WM/CSF by intensity
ordering rules.

The paper uses T1-, T2- and PD-weighted MRIs as multi-channel input; here only
the T1w is available, so clustering runs on T1w intensity alone. This is a
documented simplification -- the MIDAS-mode-only path in mrsiprep.
"""

from __future__ import annotations

import numpy as np


def fuzzy_cmeans_segment(
    t1_data: np.ndarray,
    brain_mask: np.ndarray,
    n_clusters: int = 3,
    m: float = 2.0,
    max_iter: int = 100,
    tol: float = 1e-5,
    seed: int = 0,
) -> dict[str, np.ndarray]:
    """Fuzzy c-means on T1w intensities within ``brain_mask``.

    Clusters brain voxels into ``n_clusters`` groups and merges them into
    ``{'GM', 'WM', 'CSF'}`` soft-membership maps at the input resolution
    (non-brain voxels are 0 in all three). The paper over-clusters on
    multi-channel T1/T2/PD data; with a single T1w channel, direct 3-cluster
    segmentation (the default) maps cleanly onto the three tissue classes and
    gives anatomically sensible GM/WM/CSF volume ratios, whereas over-clustering
    on one channel tends to inflate the middle (GM) class. ``n_clusters > 3`` is
    still supported (clusters are grouped to the nearest CSF/GM/WM intensity
    archetype) for experimentation.
    """
    if n_clusters < 3:
        raise ValueError(f"n_clusters must be >= 3 to merge into GM/WM/CSF, got {n_clusters}")

    t1 = np.nan_to_num(np.asarray(t1_data, dtype=np.float64).squeeze(), copy=False)
    mask = np.asarray(brain_mask, dtype=bool).squeeze()
    if t1.shape != mask.shape:
        raise ValueError(f"t1_data shape {t1.shape} does not match brain_mask shape {mask.shape}")

    intensities = t1[mask]
    if intensities.size < n_clusters:
        raise ValueError(f"Only {intensities.size} brain voxels for {n_clusters} clusters; cannot segment.")

    centroids, memberships = _fit_fcm(intensities, n_clusters, m, max_iter, tol, seed)
    tissue_masked = _merge_clusters_to_tissue(centroids, memberships)

    out: dict[str, np.ndarray] = {}
    for label, values in tissue_masked.items():
        volume = np.zeros(t1.shape, dtype=np.float32)
        volume[mask] = values.astype(np.float32)
        out[label] = volume
    return out


def _fit_fcm(
    x: np.ndarray,
    n_clusters: int,
    m: float,
    max_iter: int,
    tol: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Standard 1-D fuzzy c-means.

    Returns ``(centroids, memberships)`` where ``centroids`` has shape
    ``(n_clusters,)`` and ``memberships`` has shape ``(n_voxels, n_clusters)``.
    """
    rng = np.random.default_rng(seed)
    x = x.astype(np.float64).reshape(-1)
    n = x.size

    # Initialize centroids at evenly-spaced intensity quantiles for a stable,
    # reproducible start (rng is used only to break ties on degenerate inputs).
    quantiles = np.linspace(0.0, 1.0, n_clusters + 2)[1:-1]
    centroids = np.quantile(x, quantiles)
    centroids = centroids + rng.normal(0.0, 1e-6, size=n_clusters)

    exponent = 2.0 / (m - 1.0)
    memberships = np.full((n, n_clusters), 1.0 / n_clusters)
    for _ in range(max_iter):
        # distances: (n, n_clusters); guard against exact coincidence.
        dist = np.abs(x[:, None] - centroids[None, :])
        dist = np.maximum(dist, 1e-12)
        inv = 1.0 / (dist**exponent)
        new_memberships = inv / inv.sum(axis=1, keepdims=True)

        weights = new_memberships**m
        new_centroids = (weights * x[:, None]).sum(axis=0) / weights.sum(axis=0)

        shift = np.max(np.abs(new_centroids - centroids))
        centroids = new_centroids
        memberships = new_memberships
        if shift < tol:
            break

    order = np.argsort(centroids)
    return centroids[order], memberships[:, order]


def _merge_clusters_to_tissue(centroids: np.ndarray, memberships: np.ndarray) -> dict[str, np.ndarray]:
    """Assign intensity-ordered clusters to CSF/GM/WM and sum their memberships.

    Assumes a T1w (MPRAGE-like) contrast where CSF is darkest, GM intermediate
    and WM brightest. Clusters arrive already sorted by ascending centroid
    intensity. When over-clustering (``n_clusters > 3``), the clusters are
    grouped into CSF/GM/WM by their centroid intensity via three archetype
    anchors placed at the darkest, median and brightest centroids -- each
    cluster joins the nearest archetype. Anchoring on the actual centroid
    spread (rather than assigning all middle clusters to GM) avoids inflating
    the GM fraction when ``n_clusters`` is large.
    """
    n_clusters = centroids.shape[0]
    if n_clusters == 3:
        assignment = [0, 1, 2]  # CSF, GM, WM by ascending intensity
    else:
        anchors = np.array([centroids[0], float(np.median(centroids)), centroids[-1]])
        assignment = [int(np.argmin(np.abs(anchors - c))) for c in centroids]

    tissue_of = {0: "CSF", 1: "GM", 2: "WM"}
    out = {label: np.zeros(memberships.shape[0], dtype=np.float64) for label in ("CSF", "GM", "WM")}
    for cluster_idx, tissue_id in enumerate(assignment):
        out[tissue_of[tissue_id]] += memberships[:, cluster_idx]
    return out

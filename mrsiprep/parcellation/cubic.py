"""Cubic (grid) MNI-space parcellation.

Tiles a canonical MNI-space gray-matter mask into a regular grid of
N-millimeter cubes, generated live at whatever size ``--atlas cubic<N>mm``
requests rather than shipping one bundled file per size: a cube grid is
mechanically regenerable from its mask at any cube size, unlike an
anatomical atlas, so there is nothing size-specific worth precomputing and
storing.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

_GM_MASK_PATH = Path(__file__).resolve().parents[1] / "data" / "masks" / "mni_gm_mask.nii.gz"

_CUBIC_ATLAS_RE = re.compile(r"^cubic-?(\d+)mm$")


def parse_cubic_atlas_name(atlas: str) -> int | None:
    """Cube edge length in mm if ``atlas`` names a cubic grid (e.g.
    ``cubic10mm``/``cubic-10mm``), else ``None``."""
    match = _CUBIC_ATLAS_RE.match(atlas)
    return int(match.group(1)) if match else None


def generate_cubic_atlas(cube_size_mm: int):
    """Tile the canonical MNI-space gray-matter mask into ``cube_size_mm``
    cubes.

    Cube boundaries are anchored to the mask's own bounding box (not to
    voxel index 0), so cubes are packed tightly against the tissue they
    cover instead of being offset by an arbitrary amount of empty margin.
    A block is kept (and labelled) only if at least one of its voxels is
    inside the mask; blocks straddling the mask boundary are clipped to
    the mask, matching how a real ROI grid is normally built. Labels are
    assigned in x-major, then y, then z scan order over the block grid, so
    the same cube size always reproduces the same numbering.

    :param cube_size_mm: Cube edge length. The mask is 1mm isotropic, so
        this is also the edge length in voxels.
    :returns: An in-memory :class:`nibabel.Nifti1Image` of int32 labels, on
        the mask's own grid/affine.
    """
    import nibabel as nib

    if cube_size_mm <= 0:
        raise ValueError(f"Cubic atlas cube size must be positive, got {cube_size_mm}.")
    mask_img = nib.load(str(_GM_MASK_PATH))
    mask = np.asanyarray(mask_img.dataobj) != 0
    if not mask.any():
        raise ValueError(f"Gray-matter mask at {_GM_MASK_PATH} is empty.")

    occupied_idx = np.where(mask)
    origin = np.array([axis_idx.min() for axis_idx in occupied_idx])
    extent = np.array([axis_idx.max() for axis_idx in occupied_idx]) - origin + 1

    labels = np.zeros(mask.shape, dtype=np.int32)
    next_label = 1
    n_blocks = np.ceil(extent / cube_size_mm).astype(int)
    for bx in range(n_blocks[0]):
        x0, x1 = origin[0] + bx * cube_size_mm, min(origin[0] + (bx + 1) * cube_size_mm, mask.shape[0])
        for by in range(n_blocks[1]):
            y0, y1 = origin[1] + by * cube_size_mm, min(origin[1] + (by + 1) * cube_size_mm, mask.shape[1])
            block_xy = mask[x0:x1, y0:y1, :]
            if not block_xy.any():
                continue
            for bz in range(n_blocks[2]):
                z0, z1 = origin[2] + bz * cube_size_mm, min(origin[2] + (bz + 1) * cube_size_mm, mask.shape[2])
                block = mask[x0:x1, y0:y1, z0:z1]
                if not block.any():
                    continue
                labels[x0:x1, y0:y1, z0:z1][block] = next_label
                next_label += 1

    out = nib.Nifti1Image(labels, mask_img.affine, mask_img.header)
    out.set_data_dtype(np.int32)
    return out

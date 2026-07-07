"""Shared triplanar slice rendering and minimal HTML page helpers for per-step QC reports."""

from __future__ import annotations

from pathlib import Path

import numpy as np

PLANE_AXES = {"sagittal": 0, "coronal": 1, "axial": 2}

STYLE = (
    "body{font-family:Arial,sans-serif;margin:2rem;line-height:1.4}"
    "table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:4px 8px}"
    "code{background:#f3f3f3;padding:2px 4px}"
    "img{max-width:100%;border:1px solid #ddd}"
    ".row{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem}"
    ".row > div{flex:1 1 0}"
    ".col{display:flex;flex-direction:column;gap:1rem;margin-bottom:1rem}"
)


def load_canonical_data(path) -> np.ndarray:
    """Load a NIfTI file reoriented to closest-canonical (RAS) axes.

    Source MRSI/T1w/MNI images don't all share the same native voxel-axis
    orientation, so slicing raw arrays directly (as ``triplanar_slices`` does)
    would show some volumes flipped/rotated relative to others. Reorienting
    via the affine here keeps slice orientation consistent across callers.
    """
    import nibabel as nib

    return nib.as_closest_canonical(nib.load(str(path))).get_fdata()


def triplanar_slices(volume_data: np.ndarray, center_ijk: tuple[int, int, int] | None = None) -> dict[str, np.ndarray]:
    volume_data = np.squeeze(volume_data)
    if center_ijk is None:
        center_ijk = tuple(dimension // 2 for dimension in volume_data.shape[:3])
    i, j, k = center_ijk
    return {
        "sagittal": np.rot90(volume_data[i, :, :]),
        "coronal": np.rot90(volume_data[:, j, :]),
        "axial": np.rot90(volume_data[:, :, k]),
    }


OUTLINE_COLORS = (
    "lime", "red", "yellow", "cyan", "magenta", "orange",
    "dodgerblue", "springgreen", "gold", "deeppink", "turquoise", "orchid",
)


def label_outline_overlay(ax, label_slice: np.ndarray, colors=OUTLINE_COLORS, linewidth: float = 0.8) -> None:
    from skimage import measure

    label_values = [value for value in np.unique(label_slice) if value != 0]
    for index, label_value in enumerate(label_values):
        mask = (label_slice == label_value).astype(float)
        color = colors[index % len(colors)]
        for contour in measure.find_contours(mask, level=0.5):
            ax.plot(contour[:, 1], contour[:, 0], color=color, linewidth=linewidth)


def render_triplanar_png(
    background_slices: dict[str, np.ndarray],
    out_path: str | Path,
    overlay_slices: dict[str, np.ndarray] | None = None,
    mode: str | None = None,
    cmap: str = "gray",
    overlay_cmap: str = "magma",
    titles: dict[str, str] | None = None,
    colorbar_label: str | None = None,
) -> Path:
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    planes = ["coronal", "axial", "sagittal"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)
    overlay_image = None
    background_image = None
    for ax, plane in zip(axes, planes):
        background_image = ax.imshow(background_slices[plane], cmap=cmap)
        if overlay_slices is not None and mode == "outline":
            label_outline_overlay(ax, overlay_slices[plane])
        elif overlay_slices is not None and mode == "alpha":
            overlay_image = ax.imshow(overlay_slices[plane], cmap=overlay_cmap, alpha=0.5)
        elif overlay_slices is not None and mode == "solid":
            masked = np.ma.masked_equal(overlay_slices[plane], 0)
            overlay_image = ax.imshow(masked, cmap=overlay_cmap)
        ax.set_title((titles or {}).get(plane, plane.capitalize()))
        ax.axis("off")
    colorbar_image = overlay_image if overlay_image is not None else (background_image if overlay_slices is None else None)
    if colorbar_image is not None and colorbar_label is not None:
        fig.colorbar(colorbar_image, ax=axes, fraction=0.025, pad=0.02, label=colorbar_label)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def html_page(title: str, sections: list[tuple[str, str]]) -> str:
    lines = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><title>" + title + "</title>",
        f"<style>{STYLE}</style>",
        "</head><body>",
        f"<h1>{title}</h1>",
    ]
    for heading, body in sections:
        lines.append(f"<h2>{heading}</h2>")
        lines.append(body)
    lines.append("</body></html>")
    return "\n".join(lines)

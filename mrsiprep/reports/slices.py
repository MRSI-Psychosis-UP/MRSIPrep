"""Shared triplanar slice rendering and minimal HTML page helpers for per-step QC reports."""

from __future__ import annotations

from pathlib import Path

import numpy as np

STYLE = (
    "body{font-family:Arial,sans-serif;margin:2rem;line-height:1.4}"
    "table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:4px 8px}"
    "code{background:#f3f3f3;padding:2px 4px}"
    "img{max-width:100%;border:1px solid #ddd}"
    # <object> (used for the hover-to-flicker SVG reportlets, see
    # _svg_object_html in registration_overview.py) has no intrinsic-size
    # fallback like <img>'s max-width above -- without an explicit width it
    # renders at the embedded SVG's own point-based width/height from
    # matplotlib's figsize, which is far smaller than the available page
    # width. width:100% makes it fill the column like every other reportlet.
    ".svg-reportlet{width:100%;border:1px solid #ddd}"
    ".row{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem}"
    ".row > div{flex:1 1 0}"
    ".col{display:flex;flex-direction:column;gap:1rem;margin-bottom:1rem}"
)


def svg_object_html(svg_path: Path) -> str:
    """Embed an SVG reportlet via <object>, not <img>: only <object> reliably
    runs the CSS hover-to-flicker animation baked into the SVG itself (see
    render_triplanar_svg_flicker/render_multi_slice_triplanar_svg_flicker/
    render_axial_before_after_svg_flicker) -- an <img> sandboxes the SVG and
    some browsers won't animate it. Matches fMRIPrep's own reportlet markup
    (`class="svg-reportlet"`).
    """
    return (
        f"<div class='reportlet'><object class='svg-reportlet' type='image/svg+xml' "
        f"data='figures/{svg_path.name}'>"
        f"Problem loading figure figures/{svg_path.name}. Try reloading the report."
        f"</object></div>"
        f"<small>Get figure file: <a href='figures/{svg_path.name}' target='_blank'>figures/{svg_path.name}</a></small>"
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


def load_canonical_data_with_affine(path) -> tuple[np.ndarray, np.ndarray]:
    """Like :func:`load_canonical_data`, but also returns the (reoriented)
    affine -- needed to label slices by their physical mm coordinate (as
    fMRIPrep's reports do: ``z=-2``, ``x=10``, ``y=27``) instead of a raw,
    not-comparable-across-subjects voxel index.
    """
    import nibabel as nib

    canonical = nib.as_closest_canonical(nib.load(str(path)))
    return canonical.get_fdata(), canonical.affine


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


def center_weighted_slice_indices(size: int, n_slices: int) -> np.ndarray:
    """``n_slices`` indices spanning ``[0, size-1]``, denser near the
    center and sparser toward the edges -- a cosine warp of an otherwise
    even spacing, matching the fact that a 3D-MRSI slab's real, usable
    signal concentrates around its center while edge slices are mostly
    outside true acquisition coverage (SNR falls off sharply there), so
    the interesting range deserves more samples than the empty extremes.
    """
    if size <= 1:
        return np.zeros(1, dtype=int)
    linear = np.linspace(-1.0, 1.0, n_slices)
    # sign(x) * (1 - cos(pi*|x|/2)) rescales [-1, 1] so points cluster near
    # 0 and spread out near +-1, while endpoints stay fixed at +-1.
    warped = np.sign(linear) * (1.0 - np.cos(np.pi * np.abs(linear) / 2.0))
    positions = (warped + 1.0) / 2.0 * (size - 1)
    return np.unique(np.round(positions).astype(int))


def axial_slices_center_weighted(volume_data: np.ndarray, n_slices: int, reference: np.ndarray | None = None):
    """Up to ``n_slices`` axial (axis=2 on RAS-canonical data) 2D slices of
    ``volume_data`` at center-weighted indices, skipping any slice that's
    entirely empty in ``reference`` (``volume_data`` itself, if none given)
    -- common at the very edges of a padded grid. Returns a list of
    ``(index, rotated_2d_slice)`` pairs.
    """
    check = reference if reference is not None else volume_data
    size = volume_data.shape[2]
    candidate_indices = center_weighted_slice_indices(size, n_slices)
    slices = []
    for index in candidate_indices:
        check_plane = np.take(check, index, axis=2)
        if not np.any(check_plane > 0):
            continue
        slices.append((int(index), np.rot90(np.take(volume_data, index, axis=2))))
    if slices:
        return slices
    fallback_index = int(candidate_indices[len(candidate_indices) // 2])
    return [(fallback_index, np.rot90(np.take(volume_data, fallback_index, axis=2)))]


def axial_slice_indices_by_mask_count(mask: np.ndarray, n_slices: int, fallback: np.ndarray) -> list[int]:
    """Up to ``n_slices`` axial indices, ranked by how many ``True`` voxels
    ``mask`` has on that slice (most first), so a montage actually shows
    where the flagged voxels are rather than an anatomy-driven center
    weighting that may miss them entirely. Falls back to
    :func:`center_weighted_slice_indices` (restricted to ``fallback``'s
    nonzero slices) to pad out to ``n_slices`` when ``mask`` is empty or has
    fewer than ``n_slices`` populated slices, so the montage width stays
    consistent even on a metabolite with few or no flagged voxels.
    """
    mask = np.squeeze(mask)
    counts = mask.sum(axis=(0, 1))
    ranked = [int(index) for index in np.argsort(counts)[::-1] if counts[index] > 0]
    ranked = ranked[:n_slices]
    if len(ranked) < n_slices:
        fallback_indices = [index for index, _ in axial_slices_center_weighted(fallback, n_slices)]
        for index in fallback_indices:
            if len(ranked) >= n_slices:
                break
            if index not in ranked:
                ranked.append(index)
    return sorted(ranked)


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


def mask_contour_overlay(ax, mask_slice: np.ndarray, color: str = "#00e5ff", level: float = 0.5, linewidth: float = 0.8) -> None:
    """Single-colour contour of one binary/probabilistic mask slice (e.g. a
    white-matter probseg thresholded at ``level``) -- unlike
    :func:`label_outline_overlay`, which rainbow-colours each distinct label
    in a multi-label segmentation, this always draws in one ``color``. Light
    blue by default (not fMRIPrep's own red): the alignment figures here use
    red/orange-heavy "magma" colormaps for the metabolite overlay itself,
    which a red contour disappears into -- picked interactively against the
    real rendered data (see mrsiprep/reports/slices.py git history for the
    colorpicker tool used).
    """
    from skimage import measure

    for contour in measure.find_contours(mask_slice, level=level):
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
    vmin: float | None = None,
    vmax: float | None = None,
) -> Path:
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    planes = ["coronal", "axial", "sagittal"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)
    overlay_image = None
    background_image = None
    for ax, plane in zip(axes, planes):
        background_image = ax.imshow(background_slices[plane], cmap=cmap, vmin=vmin, vmax=vmax)
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


_PLANE_AXES = {"sagittal": 0, "coronal": 1, "axial": 2}


def _occupied_slice_indices(volume: np.ndarray, axis: int, n_slices: int) -> list[int]:
    """``n_slices`` indices spanning the slices along ``axis`` that actually
    contain nonzero data.

    Spanning the raw array extent instead would spend much of the montage on
    the empty padding a resampled/padded grid carries at each end.
    """
    other_axes = tuple(a for a in range(volume.ndim) if a != axis)
    occupied = np.flatnonzero(np.any(volume != 0, axis=other_axes))
    if occupied.size == 0:
        low, high = 0, volume.shape[axis] - 1
    else:
        low, high = int(occupied[0]), int(occupied[-1])
    if high <= low:
        return [low] * n_slices
    return sorted({int(round(value)) for value in np.linspace(low, high, n_slices)})


def render_multi_slice_triplanar_png(
    background: np.ndarray,
    out_path: str | Path,
    overlay: np.ndarray | None = None,
    mode: str | None = None,
    cmap: str = "gray",
    overlay_cmap: str = "magma",
    colorbar_label: str | None = None,
    n_slices: int = 8,
) -> Path:
    """Coronal / axial / sagittal, ``n_slices`` slices per plane instead of
    one -- a single center slice can land on an unremarkable part of the
    registration and miss a real misalignment a few slices away.

    ``background``/``overlay`` are full 3D (canonical-orientation) volumes,
    not pre-sliced dicts like :func:`render_triplanar_png` takes: slice
    selection happens per plane here, so the whole volume is needed.

    Slice indices are chosen from ``overlay`` when one is given, not from
    ``background``: a full-head template is nonzero almost everywhere
    (scalp, neck), so indexing off it spends most of the montage on
    anatomy the overlay doesn't even reach. The whole point of the montage
    is to see where the overlay actually lands, so that is what decides
    which slices are worth showing.
    """
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    background = np.squeeze(background)
    overlay_arr = np.squeeze(overlay) if overlay is not None else None
    index_source = overlay_arr if overlay_arr is not None else background

    # One shared scale across every panel, from the overlay's own data:
    # per-imshow auto-scaling (the default with vmin/vmax left unset) gives
    # each slice its own colour scale, so the same signal level looks
    # different from panel to panel and the numbers on the shared colorbar
    # stop meaning anything.
    vmin = vmax = None
    if overlay_arr is not None and mode in ("alpha", "solid"):
        finite = overlay_arr[np.isfinite(overlay_arr) & (overlay_arr != 0)]
        vmin = 0.0
        vmax = float(np.percentile(finite, 99)) if finite.size else 1.0
        vmax = max(vmax, vmin + 1e-6)

    planes = ("coronal", "axial", "sagittal")
    fig, axes = plt.subplots(
        len(planes), n_slices, figsize=(1.7 * n_slices, 1.9 * len(planes)), squeeze=False, constrained_layout=True
    )
    overlay_image = None
    for row, plane in enumerate(planes):
        axis = _PLANE_AXES[plane]
        indices = _occupied_slice_indices(index_source, axis, n_slices)
        for col in range(n_slices):
            ax = axes[row][col]
            if col >= len(indices):
                ax.axis("off")
                continue
            index = indices[col]
            bg_slice = np.rot90(np.take(background, index, axis=axis))
            ax.imshow(bg_slice, cmap=cmap)
            if overlay_arr is not None:
                ov_slice = np.rot90(np.take(overlay_arr, index, axis=axis))
                if mode == "outline":
                    label_outline_overlay(ax, ov_slice)
                elif mode == "alpha":
                    overlay_image = ax.imshow(ov_slice, cmap=overlay_cmap, alpha=0.5, vmin=vmin, vmax=vmax)
                elif mode == "solid":
                    overlay_image = ax.imshow(np.ma.masked_equal(ov_slice, 0), cmap=overlay_cmap, vmin=vmin, vmax=vmax)
            ax.set_title(f"{index}", fontsize=7)
            ax.axis("off")
        axes[row][0].axis("on")
        axes[row][0].set_xticks([])
        axes[row][0].set_yticks([])
        axes[row][0].set_ylabel(plane.capitalize(), fontsize=9)
    if overlay_image is not None and colorbar_label is not None:
        fig.colorbar(overlay_image, ax=axes.ravel().tolist(), shrink=0.7, pad=0.01, label=colorbar_label)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def render_axial_overlay_montage(
    background: np.ndarray,
    overlay: np.ndarray,
    out_path: str | Path,
    label: str,
    overlay_cmap: str = "magma",
    n_slices: int = 10,
) -> Path:
    """Single-row axial montage of ``overlay`` (solid, zeros masked out) on
    ``background``, at equally-spaced slices chosen from ``overlay``'s own
    extent (see :func:`axial_slices_center_weighted`) -- same presentation
    as the MRSI Raw/PVC tabs' per-metabolite montages
    (:mod:`mrsiprep.reports.mrsi_raw_overview`), reused here for the
    per-metabolite alignment montages in the T1w-space/Template-space tabs.
    """
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    background = np.squeeze(background)
    overlay_arr = np.squeeze(overlay)

    finite = overlay_arr[np.isfinite(overlay_arr) & (overlay_arr != 0)]
    vmin = 0.0
    vmax = float(np.percentile(finite, 99)) if finite.size else 1.0
    vmax = max(vmax, vmin + 1e-6)

    slices = axial_slices_center_weighted(overlay_arr, n_slices)
    n = len(slices)
    fig, axes = plt.subplots(1, n, figsize=(1.8 * n, 2.2), constrained_layout=True)
    if n == 1:
        axes = [axes]
    overlay_image = None
    for ax, (index, _) in zip(axes, slices):
        bg_slice = np.rot90(np.take(background, index, axis=2))
        ov_slice = np.rot90(np.take(overlay_arr, index, axis=2))
        ax.imshow(bg_slice, cmap="gray")
        overlay_image = ax.imshow(np.ma.masked_equal(ov_slice, 0), cmap=overlay_cmap, vmin=vmin, vmax=vmax)
        ax.set_title(f"z={index}", fontsize=8)
        ax.axis("off")
    if overlay_image is not None:
        fig.colorbar(overlay_image, ax=axes, fraction=0.02, pad=0.02, label=label)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


_SVG_ID_REF_ATTRS = ("clip-path", "fill", "stroke", "mask", "filter", "marker-start", "marker-mid", "marker-end")
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_SVG_HREF = "{http://www.w3.org/2000/svg}href"


def _prefix_svg_ids(root, prefix: str) -> None:
    """Rewrite every ``id`` attribute in an SVG tree and every reference to
    it (``url(#...)`` in clip-path/fill/stroke/mask/filter/marker-* and
    ``xlink:href="#..."``/``href="#..."``) to carry ``prefix``, in place.

    Needed because matplotlib numbers element ids ("figure_1", "axes_1",
    clip-path hashes, ...) independently per rendered document, starting
    fresh each time -- two separately-rendered documents collide on the
    exact same ids once merged into one SVG, which is invalid SVG and
    produces undefined/broken rendering (confirmed empirically: duplicate
    "figure_1"/"axes_1-3" ids corrupted a merged document's layout).
    """
    import re

    old_ids = {element.get("id") for element in root.iter() if element.get("id")}
    if not old_ids:
        return
    id_pattern = re.compile(r"\b(" + "|".join(re.escape(old_id) for old_id in old_ids) + r")\b")

    for element in root.iter():
        element_id = element.get("id")
        if element_id in old_ids:
            element.set("id", prefix + element_id)
        for attr in _SVG_ID_REF_ATTRS:
            value = element.get(attr)
            if value and "#" in value:
                element.set(attr, id_pattern.sub(lambda m: prefix + m.group(1), value))
        for href_attr in (_XLINK_HREF, _SVG_HREF, "href"):
            value = element.get(href_attr)
            if value and value.startswith("#") and value[1:] in old_ids:
                element.set(href_attr, "#" + prefix + value[1:])
        if element.text and "url(#" in element.text:
            element.text = id_pattern.sub(lambda m: prefix + m.group(1), element.text)


def compose_flicker_svg(background_svg: str, foreground_svg: str, out_path: str | Path, flicker_id: str) -> Path:
    """Merge two standalone SVG documents into one fMRIPrep-style hover-to-flicker
    reportlet: ``background_svg`` (e.g. T1w/template) stays static,
    ``foreground_svg`` (e.g. the MRSI overlay, rendered with a transparent
    background) fades in and out on hover via a pure-CSS ``@keyframes``
    animation, paused until ``:hover``. No JS, no new dependency: matplotlib
    already emits SVG natively via ``savefig(..., format="svg")``, and the
    two documents are merged with the stdlib's ``xml.etree.ElementTree``
    rather than niworkflows' svgutils (see this module's reasoning for not
    adding niworkflows as a dependency for one reportlet).

    ``flicker_id`` must be unique per rendered figure on a page: the
    ``@keyframes`` name is scoped to the whole HTML document, so two
    reportlets sharing one name would have their animations collide/restart
    each other.

    :param background_svg: Raw SVG document text for the static layer.
    :param foreground_svg: Raw SVG document text for the layer that
        flickers on hover; render it with a transparent background so the
        background layer shows through everywhere the overlay has no data.
    :param out_path: Where to write the composed SVG.
    :param flicker_id: Unique suffix for the CSS animation name.
    :returns: ``out_path``.
    """
    import xml.etree.ElementTree as ET

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

    bg_root = ET.fromstring(background_svg)
    fg_root = ET.fromstring(foreground_svg)

    # matplotlib numbers ids ("figure_1", "axes_1", clip-path hashes, ...)
    # independently per document, starting fresh each time -- so the two
    # layers collide on the exact same ids once merged into one SVG
    # (confirmed: "figure_1"/"axes_1-3" duplicated, which broke rendering --
    # duplicate ids are invalid SVG and renderer behaviour is undefined).
    # Prefix every id and every reference to it so the two layers can never
    # collide, regardless of what matplotlib happened to number things.
    _prefix_svg_ids(bg_root, "bg-")
    _prefix_svg_ids(fg_root, "fg-")

    # matplotlib always emits a single top-level viewBox; both layers share
    # the same figure size/DPI, so the background's is authoritative.
    view_box = bg_root.get("viewBox", "0 0 100 100")
    width, height = bg_root.get("width"), bg_root.get("height")

    # xmlns/xmlns:xlink are emitted automatically from the registered
    # namespaces above + the namespaced "svg" tag below; setting them again
    # explicitly here would write duplicate xmlns attributes.
    svg_ns = "{http://www.w3.org/2000/svg}"
    composed = ET.Element(
        f"{svg_ns}svg",
        {
            "version": "1.1",
            "viewBox": view_box,
            "preserveAspectRatio": "xMidYMid meet",
        },
    )
    if width:
        composed.set("width", width)
    if height:
        composed.set("height", height)

    style = ET.SubElement(composed, f"{svg_ns}style")
    style.set("type", "text/css")
    style.text = (
        f"@keyframes flicker-{flicker_id} {{ 0% {{opacity: 1;}} 100% {{opacity: 0;}} }}"
        f".flicker-fg-{flicker_id} {{ animation: 1s ease-in-out 0s alternate none infinite paused flicker-{flicker_id}; }}"
        f".flicker-fg-{flicker_id}:hover {{ animation-play-state: running; }}"
    )

    bg_group = ET.SubElement(composed, f"{svg_ns}g", {"class": "background-svg"})
    bg_group.extend(list(bg_root))

    fg_group = ET.SubElement(composed, f"{svg_ns}g", {"class": f"foreground-svg flicker-fg-{flicker_id}"})
    fg_group.extend(list(fg_root))

    ET.ElementTree(composed).write(out_path, encoding="unicode", xml_declaration=False)
    return out_path


def compose_layered_crossfade_svg(
    base_svg: str,
    layers: list[tuple[str, list[tuple[float, float]]]],
    out_path: str | Path,
    cycle_id: str,
    total_seconds: float,
) -> Path:
    """Merge one permanently-opaque base document with N independently-
    fading transparent layers into one hover-to-cycle, smoothly-crossfading
    reportlet -- same interaction model as :func:`compose_flicker_svg`
    (paused until :hover, nothing animates on page load), just with a
    multi-stop crossfade instead of a single two-layer fade.

    Each layer in ``layers`` fades in/out on its own CSS ``@keyframes``
    opacity track -- plain (non-``steps()``) percentage keyframes, so the
    browser interpolates between consecutive stops and the transitions
    genuinely crossfade rather than jumping between discrete frames.
    Opacity only ever *adds* a transparent layer's content on
    top of what's already visible; it can never subtract something the
    base already drew. So anything one state of the cycle must NOT show
    that an earlier state did (e.g. a contour drawn in the base) cannot be
    hidden this way -- the base must be the state every frame has in
    common (typically the plain anatomy alone), with every difference
    between frames expressed as a separate fading layer on top of it.

    All layers pause/resume together on a single hover region covering the
    whole composed figure (a wrapping ``<g>``, not each layer's own,
    possibly-transparent-at-that-instant area) -- hovering anywhere over
    the image starts every layer's animation in sync, and leaving freezes
    all of them wherever they were, same as :func:`compose_flicker_svg`
    (no special reset-on-leave logic; `animation-play-state: paused` holds
    the current computed frame, it does not rewind to 0%).

    :param base_svg: Raw SVG document text for the permanent, fully-opaque
        base layer (rendered non-transparent).
    :param layers: ``(layer_svg, keyframe_stops)`` pairs, each rendered
        with a transparent background. ``keyframe_stops`` is a list of
        ``(percent, opacity)`` tuples (0-100, 0.0-1.0); CSS linearly
        interpolates opacity between consecutive stops. Must include a
        ``(0, ...)`` and a ``(100, ...)`` stop (not enforced here -- an
        incomplete track just holds its first/last given value past the
        ends, which is almost certainly not the intended animation).
    :param out_path: Where to write the composed SVG.
    :param cycle_id: Unique suffix for the CSS animation name (same
        uniqueness requirement as ``flicker_id`` in :func:`compose_flicker_svg`).
    :param total_seconds: Duration of one full cycle before it loops.
    :returns: ``out_path``.
    """
    import xml.etree.ElementTree as ET

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not layers:
        raise ValueError("compose_layered_crossfade_svg needs at least 1 fading layer")

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

    base_root = ET.fromstring(base_svg)
    _prefix_svg_ids(base_root, "base-")
    layer_roots = [ET.fromstring(svg) for svg, _ in layers]
    for index, root in enumerate(layer_roots):
        _prefix_svg_ids(root, f"l{index}-")

    view_box = base_root.get("viewBox", "0 0 100 100")
    width, height = base_root.get("width"), base_root.get("height")

    svg_ns = "{http://www.w3.org/2000/svg}"
    composed = ET.Element(
        f"{svg_ns}svg",
        {"version": "1.1", "viewBox": view_box, "preserveAspectRatio": "xMidYMid meet"},
    )
    if width:
        composed.set("width", width)
    if height:
        composed.set("height", height)

    style = ET.SubElement(composed, f"{svg_ns}style")
    style.set("type", "text/css")
    hover_root_class = f"cycle-hover-root-{cycle_id}"
    keyframes_css = ""
    layer_css = ""
    for index, (_, stops) in enumerate(layers):
        stop_rules = " ".join(f"{pct:.4f}% {{opacity: {opacity};}}" for pct, opacity in stops)
        keyframes_css += f"@keyframes cycle-{cycle_id}-{index} {{ {stop_rules} }}"
        # paused by default (nothing animates on page load, matching
        # compose_flicker_svg) -- the whole-figure hover rule below is what
        # starts every layer's animation together.
        layer_css += (
            f".cycle-layer-{cycle_id}-{index} {{ "
            f"animation: {total_seconds:.3f}s linear 0s infinite paused cycle-{cycle_id}-{index}; }}"
        )
    # One hover rule, scoped to the whole-figure wrapper (not each layer's
    # own, possibly near-transparent-at-that-instant area) resumes every
    # layer's animation in sync -- see the docstring for why this must be
    # a single shared hover region rather than one :hover per layer.
    hover_selectors = ", ".join(f".{hover_root_class}:hover .cycle-layer-{cycle_id}-{i}" for i in range(len(layers)))
    layer_css += f"{hover_selectors} {{ animation-play-state: running; }}"
    style.text = keyframes_css + layer_css

    hover_root = ET.SubElement(composed, f"{svg_ns}g", {"class": hover_root_class})

    base_group = ET.SubElement(hover_root, f"{svg_ns}g", {"class": "cycle-base"})
    base_group.extend(list(base_root))

    for index, root in enumerate(layer_roots):
        group = ET.SubElement(hover_root, f"{svg_ns}g", {"class": f"cycle-layer-{cycle_id}-{index}"})
        group.extend(list(root))

    ET.ElementTree(composed).write(out_path, encoding="unicode", xml_declaration=False)
    return out_path


def render_triplanar_svg_flicker(
    background_slices: dict[str, np.ndarray],
    out_path: str | Path,
    overlay_slices: dict[str, np.ndarray],
    flicker_id: str,
    overlay_mode: str = "alpha",
    cmap: str = "gray",
    overlay_cmap: str = "magma",
    titles: dict[str, str] | None = None,
    colorbar_label: str | None = None,
) -> Path:
    """SVG counterpart of :func:`render_triplanar_png`: same single-slice
    triplanar layout, but the background (anatomy) and overlay (MRSI) are
    rendered as two separate figures and merged via
    :func:`compose_flicker_svg` so the overlay fades in/out on hover
    instead of being permanently alpha-blended into one flat raster.
    """
    import io

    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    planes = ["coronal", "axial", "sagittal"]

    def _render(slices_by_plane, *, overlay=None, transparent=False, fixed_positions=None):
        fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=(fixed_positions is None))
        overlay_image = None
        background_image = None
        for ax, plane in zip(axes, planes):
            if overlay is None:
                background_image = ax.imshow(slices_by_plane[plane], cmap=cmap)
            else:
                ax.imshow(np.zeros_like(slices_by_plane[plane]), cmap="gray", alpha=0.0)
                if overlay_mode == "outline":
                    label_outline_overlay(ax, overlay[plane])
                elif overlay_mode == "alpha":
                    overlay_image = ax.imshow(overlay[plane], cmap=overlay_cmap, alpha=1.0)
                elif overlay_mode == "solid":
                    masked = np.ma.masked_equal(overlay[plane], 0)
                    overlay_image = ax.imshow(masked, cmap=overlay_cmap)
            ax.set_title((titles or {}).get(plane, plane.capitalize()))
            ax.axis("off")
        if colorbar_label is not None:
            # constrained_layout recomputes each axes' position from what is
            # actually drawn: a colorbar on only one of the two layers
            # (foreground has one, background doesn't) reflows that layer's
            # panel geometry differently, so the two layers' axes stop
            # lining up once merged (confirmed empirically -- the sagittal
            # panel visibly shifted/shrank between layers). Reserve the same
            # colorbar space in both by drawing one on the background too,
            # from its own imshow, then hiding it -- same layout, no
            # visible duplicate colorbar.
            mappable = overlay_image if overlay_image is not None else background_image
            cbar = fig.colorbar(mappable, ax=axes, fraction=0.025, pad=0.02, label=colorbar_label)
            if overlay_image is None:
                cbar.ax.set_visible(False)
        if fixed_positions is None:
            # Even with matching colorbar space reserved in both layers,
            # two independent constrained_layout solves aren't guaranteed
            # to agree pixel-for-pixel (confirmed empirically on the
            # multi-slice renderer). Solve once here, then pin the
            # foreground layer to these exact positions below so the two
            # documents stay aligned once composited.
            fig.canvas.draw()
            positions = [ax.get_position().frozen() for ax in axes]
        else:
            for ax, pos in zip(axes, fixed_positions):
                ax.set_position(pos)
            positions = fixed_positions
        buf = io.BytesIO()
        fig.savefig(buf, format="svg", transparent=transparent)
        plt.close(fig)
        return buf.getvalue().decode(), positions

    background_doc, positions = _render(background_slices)
    foreground_doc, _ = _render(background_slices, overlay=overlay_slices, transparent=True, fixed_positions=positions)
    return compose_flicker_svg(background_doc, foreground_doc, out_path, flicker_id)


_PLANE_COORD_LETTER = {"sagittal": "x", "coronal": "y", "axial": "z"}
# RAS axis order: L/R markers only apply to the planes whose in-slice
# horizontal axis is left-right (coronal, axial) -- a sagittal slice's
# horizontal axis is anterior-posterior, which has no L/R meaning.
_PLANES_WITH_LR_MARKERS = ("coronal", "axial")


def _voxel_index_to_mm(affine: np.ndarray, plane: str, index: int) -> float:
    """Physical mm coordinate of voxel ``index`` along ``plane``'s axis, at
    the canonical-RAS origin on the other two axes (matches what fMRIPrep's
    own slice labels report: the coordinate is meaningful regardless of the
    other two axes' position since the affine is diagonal/near-diagonal for
    a canonical-oriented image)."""
    voxel = np.zeros(4)
    voxel[_PLANE_AXES[plane]] = index
    voxel[3] = 1
    mm = affine @ voxel
    return float(mm[_PLANE_AXES[plane]])


def _panel_title(affine: np.ndarray | None, plane: str, index: int) -> str:
    """Panel title for one multi-slice montage cell: the physical mm
    coordinate (``z=-2``, matching fMRIPrep's own report style) when
    ``affine`` is known, or the bare voxel index as a fallback when it
    isn't (a voxel index alone isn't comparable across subjects/resolutions,
    but is still better than no label at all)."""
    if affine is None:
        return f"{index}"
    mm = _voxel_index_to_mm(affine, plane, index)
    return f"{_PLANE_COORD_LETTER[plane]}={mm:.0f}"


def render_multi_slice_triplanar_svg_flicker(
    background: np.ndarray,
    out_path: str | Path,
    overlay: np.ndarray,
    flicker_id: str,
    overlay_mode: str = "solid",
    cmap: str = "gray",
    overlay_cmap: str = "magma",
    colorbar_label: str | None = None,
    n_slices: int = 8,
    affine: np.ndarray | None = None,
    wm_mask: np.ndarray | None = None,
    size_scale: float = 1.8,
) -> Path:
    """SVG counterpart of :func:`render_multi_slice_triplanar_png`: same
    coronal/axial/sagittal montage, but composed as a hover-to-flicker
    reportlet via :func:`compose_flicker_svg` instead of one flat alpha
    blend. Slice selection, shared vmin/vmax, and the overlay colour scale
    all match the PNG version exactly -- see its docstring for why slices
    are chosen from the overlay's extent rather than the background's.

    ``affine`` (the canonical-RAS affine of ``background``/``overlay``, as
    returned by :func:`load_canonical_data_with_affine`) labels each panel
    with its physical mm coordinate (``z=-2``, ``x=10``, ``y=27``, matching
    fMRIPrep's own report style) instead of a raw voxel index, which isn't
    comparable across subjects/resolutions. Left/right markers are drawn on
    coronal and axial panels (radiological-irrelevant here: canonical RAS
    means the left side of the array is the subject's left).

    ``wm_mask``, when given, must be on the same grid as ``background``/
    ``overlay`` -- its contour (see :func:`mask_contour_overlay`; light blue,
    not fMRIPrep's own red, since the overlay colormap here is red/orange-
    heavy) is drawn at the same pixel position on every panel it appears on,
    like the L/R markers and titles. With a mask, the reportlet becomes a
    hover-to-cycle, smoothly crossfading figure (via
    :func:`compose_layered_crossfade_svg`, not the 2-layer hover-flicker
    used otherwise): anatomy+contour, then anatomy+contour+MRSI, then
    anatomy+MRSI alone with no contour, looping back to the first while
    hovered. The third state exists because the contour can distract from
    judging the anat/MRSI alignment on its own. Without a mask, there's
    nothing to add a third state between, so this falls back to the plain
    2-layer hover-to-flicker (anatomy <-> anatomy+MRSI) as before.

    The colorbar is drawn directly into its own dedicated grid column (via
    ``cax=``, not ``fig.colorbar(..., ax=...)``) -- the latter steals space
    from whichever axes it's given rather than using a pre-reserved cell,
    which (confirmed empirically, both on its own and combined with
    constrained_layout) overlapped and obscured a slice panel's image.
    """
    import io

    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    background = np.squeeze(background)
    overlay_arr = np.squeeze(overlay)
    wm_mask_arr = np.squeeze(wm_mask) if wm_mask is not None else None

    vmin = vmax = None
    if overlay_mode in ("alpha", "solid"):
        finite = overlay_arr[np.isfinite(overlay_arr) & (overlay_arr != 0)]
        vmin = 0.0
        vmax = float(np.percentile(finite, 99)) if finite.size else 1.0
        vmax = max(vmax, vmin + 1e-6)

    planes = ("coronal", "axial", "sagittal")
    indices_by_plane = {plane: _occupied_slice_indices(overlay_arr, _PLANE_AXES[plane], n_slices) for plane in planes}
    # One extra, narrower column reserved solely for the colorbar. Narrow:
    # with cax=cbar_ax below, the colorbar fills this cell's full height and
    # width (no shrink/fraction to compensate), so the column itself must
    # already be colorbar-proportioned, not slice-panel-proportioned.
    cbar_col_width = 0.3
    width_ratios = [1.0] * n_slices + [cbar_col_width]

    def _render(
        *,
        layer_content: str,
        transparent: bool,
        fixed_positions: list | None,
    ) -> tuple[str, list]:
        """``layer_content``: "anatomy" (background only), "overlay" (MRSI
        overlay only -- plus anatomy underneath when not ``transparent``,
        i.e. when this is the plain 2-layer flicker's foreground, not a
        fading layer meant to composite onto a separate base), or
        "contour" (the WM mask contour alone, nothing else -- always on a
        transparent background, used only as one of the 3-frame cycle's
        independently-fading layers)."""
        fig, axes = plt.subplots(
            len(planes),
            n_slices + 1,
            figsize=(size_scale * 1.7 * n_slices, size_scale * 1.9 * len(planes)),
            squeeze=False,
            gridspec_kw={"width_ratios": width_ratios},
            # constrained_layout stays on for both passes (not just the
            # first): the colorbar axis is solved fresh by it on every
            # pass (see the pinned_axes note below), and it needs
            # constrained_layout active on the foreground pass too or its
            # tick labels/axis label have no reserved margin and clip off
            # the canvas edge (confirmed empirically). It does not fight
            # back against the manual ax.set_position() pinning applied
            # below afterwards -- a position set after layout solves holds
            # through the following savefig()'s redraw.
            constrained_layout=True,
        )
        overlay_image = None
        background_image = None
        for row, plane in enumerate(planes):
            axis = _PLANE_AXES[plane]
            indices = indices_by_plane[plane]
            for col in range(n_slices):
                ax = axes[row][col]
                if col >= len(indices):
                    ax.axis("off")
                    continue
                index = indices[col]
                if layer_content == "anatomy":
                    bg_slice = np.rot90(np.take(background, index, axis=axis))
                    background_image = ax.imshow(bg_slice, cmap=cmap)
                elif layer_content == "overlay":
                    bg_slice = np.rot90(np.take(background, index, axis=axis))
                    ov_slice = np.rot90(np.take(overlay_arr, index, axis=axis))
                    # transparent=False here means this overlay layer is
                    # the plain 2-layer flicker's foreground, composited
                    # directly onto a separately-rendered opaque background
                    # layer by the caller -- draw a transparent placeholder,
                    # not real anatomy, so that background still shows
                    # through underneath once the two are merged.
                    if not transparent and overlay_mode != "outline":
                        ax.imshow(bg_slice, cmap=cmap)
                    if overlay_mode == "outline":
                        ax.imshow(np.zeros_like(bg_slice), cmap="gray", alpha=0.0)
                        label_outline_overlay(ax, ov_slice)
                    elif overlay_mode == "alpha":
                        overlay_image = ax.imshow(ov_slice, cmap=overlay_cmap, alpha=1.0, vmin=vmin, vmax=vmax)
                    elif overlay_mode == "solid":
                        overlay_image = ax.imshow(np.ma.masked_equal(ov_slice, 0), cmap=overlay_cmap, vmin=vmin, vmax=vmax)
                else:  # "contour": nothing but a transparent placeholder + the contour itself
                    bg_slice = np.rot90(np.take(background, index, axis=axis))
                    ax.imshow(np.zeros_like(bg_slice), cmap="gray", alpha=0.0)
                if layer_content == "contour" and wm_mask_arr is not None:
                    wm_slice = np.rot90(np.take(wm_mask_arr, index, axis=axis))
                    mask_contour_overlay(ax, wm_slice)
                ax.set_title(_panel_title(affine, plane, index), fontsize=7)
                if plane in _PLANES_WITH_LR_MARKERS:
                    # Canonical RAS: array column 0 is the subject's left,
                    # the last column is their right -- independent of
                    # show_overlay/transparent so both layers carry
                    # identical, aligned markers.
                    label_kwargs = dict(transform=ax.transAxes, fontsize=6, fontweight="bold", color="white")
                    ax.text(0.02, 0.98, "L", ha="left", va="top", **label_kwargs)
                    ax.text(0.98, 0.98, "R", ha="right", va="top", **label_kwargs)
                ax.axis("off")
            axes[row][0].axis("on")
            axes[row][0].set_xticks([])
            axes[row][0].set_yticks([])
            axes[row][0].set_ylabel(plane.capitalize(), fontsize=9)
        # The dedicated colorbar column's axes are plain grid cells, not a
        # fig.colorbar(..., ax=...) target: that form carves new space out
        # of whichever axes it's given, and with constrained_layout active
        # across multiple rows it carved unpredictably (confirmed
        # empirically -- the colorbar ended up overlapping slice panels
        # instead of sitting cleanly beside them). Using the middle row's
        # cell directly as cax instead makes the colorbar exactly fill that
        # one pre-reserved cell, nothing more.
        middle_row = len(planes) // 2
        for row in range(len(planes)):
            if row != middle_row:
                # set_visible(False), not axis("off"): the latter still
                # reserves the axes for constrained_layout's bookkeeping,
                # which -- for a column it shares with the colorbar axes --
                # was silently suppressing the colorbar's own tick labels
                # and axis label (confirmed empirically: identical setup,
                # only this line changed, made "CrPCr [IU]" and its tick
                # numbers appear). set_visible(False) drops the axes from
                # that bookkeeping entirely.
                axes[row][n_slices].set_visible(False)
        cbar_ax = axes[middle_row][n_slices]
        if colorbar_label is not None:
            # Same fix as render_triplanar_svg_flicker: reserve identical
            # colorbar space in both layers so constrained_layout doesn't
            # reflow their axes differently and desync the two documents.
            mappable = overlay_image if overlay_image is not None else background_image
            if mappable is not None:
                cbar = fig.colorbar(mappable, cax=cbar_ax, label=colorbar_label)
                if overlay_image is None:
                    # Hide the background layer's colorbar (it has nothing
                    # real to show) via alpha, NOT ax.set_visible(False):
                    # the latter drops the axes from constrained_layout's
                    # bookkeeping, so it resolves a different, too-tight
                    # position than one actually rendering tick labels
                    # needs -- pinning that position onto the foreground
                    # pass (below) then clipped its real tick labels/axis
                    # label off the edge of the canvas (confirmed
                    # empirically). Full alpha=0 keeps it in the same solve
                    # as a real colorbar while rendering nothing visible.
                    for artist in (cbar.ax.yaxis.label, cbar.outline, *cbar.ax.get_yticklabels(), *cbar.ax.yaxis.get_ticklines()):
                        artist.set_alpha(0)
                    # The gradient itself is a QuadMesh (cbar.ax.collections),
                    # not an AxesImage in current matplotlib -- cbar.ax.images
                    # is always empty here, so hiding only that silently no-ops
                    # and leaves the gradient fully visible (confirmed
                    # empirically: this is what let a hidden background-layer
                    # colorbar show through once composited as this
                    # function's own permanent base layer rather than only
                    # ever appearing underneath an identically-positioned
                    # real colorbar). Hide both, whichever matplotlib used.
                    if cbar.ax.images:
                        cbar.ax.images[0].set_alpha(0)
                    for collection in cbar.ax.collections:
                        collection.set_alpha(0)
            else:
                # Neither an overlay nor a background image was drawn this
                # pass (the "contour"-only layer: nothing in its loop body
                # ever sets overlay_image/background_image) -- there is
                # nothing to put a colorbar on, so the cell would otherwise
                # be left as a bare Axes with its default visible border.
                # This pass's positions are always pinned from an earlier
                # pass (never solved here), so turning the axes fully off
                # can't desync the geometry the way it would for a pass
                # that still needs to solve its own layout.
                cbar_ax.axis("off")
        else:
            cbar_ax.axis("off")
        # The colorbar axis is pinned too (not just the slice panels): its
        # position must come from the same constrained_layout solve as the
        # slice axes it's pinned alongside, with real (if invisible, see
        # above) tick-label content -- a position solved independently per
        # pass, or with no colorbar content at all, doesn't match the one
        # pass actually displaying labels and clips them (both confirmed
        # empirically as separate failure modes).
        pinned_axes = [ax for row in axes for ax in row[: n_slices + 1]]
        if fixed_positions is None:
            # Let constrained_layout solve positions once (on the
            # background layer), then capture them so the foreground layer
            # can be pinned to the exact same geometry below -- two
            # independent constrained_layout solves are not guaranteed to
            # agree even on nominally-equivalent content (confirmed
            # empirically: axes bounding boxes differed between layers
            # despite identical figure size and an identical colorbar in
            # both), which silently misaligns the overlay once composited.
            fig.canvas.draw()
            positions = [ax.get_position().frozen() for ax in pinned_axes]
        else:
            for ax, pos in zip(pinned_axes, fixed_positions):
                ax.set_position(pos)
            positions = fixed_positions
        buf = io.BytesIO()
        fig.savefig(buf, format="svg", transparent=transparent)
        plt.close(fig)
        return buf.getvalue().decode(), positions

    if wm_mask_arr is None:
        background_doc, positions = _render(layer_content="anatomy", transparent=False, fixed_positions=None)
        foreground_doc, _ = _render(layer_content="overlay", transparent=True, fixed_positions=positions)
        return compose_flicker_svg(background_doc, foreground_doc, out_path, flicker_id)

    # Hover-to-cycle, smoothly crossfading between 3 states: anat+contour
    # -> anat+contour+MRSI -> anat+MRSI (no contour) -> back to anat+contour.
    # The anatomy-only pass is the permanently-opaque base (every state
    # shows it); the contour and the MRSI overlay are two independently-
    # fading transparent layers on top, each on its own opacity track, so
    # the transitions genuinely crossfade instead of jumping between
    # discrete frames. Positions are solved once on the base and pinned on
    # the other two so all three stay pixel-aligned, same reasoning as the
    # two-layer flicker case above.
    anatomy_doc, positions = _render(layer_content="anatomy", transparent=False, fixed_positions=None)
    contour_doc, _ = _render(layer_content="contour", transparent=True, fixed_positions=positions)
    overlay_doc, _ = _render(layer_content="overlay", transparent=True, fixed_positions=positions)

    hold_seconds, fade_seconds = 1.0, 0.4
    segment = hold_seconds + fade_seconds
    total = 3 * segment

    def _pct(t: float) -> float:
        return 100 * (t % total) / total

    # Segment 0 [0, segment): contour on, overlay off ("anat+contour").
    # Segment 1 [segment, 2*segment): contour on, overlay on ("+MRSI").
    # Segment 2 [2*segment, total): contour off, overlay on ("anat+MRSI").
    # Each segment holds for hold_seconds then crossfades for fade_seconds
    # into the next -- the two tracks only ever move during the fade
    # windows between segments, each other's "hold" value elsewhere.
    contour_stops = [
        (_pct(0), 1), (_pct(hold_seconds), 1),  # segment 0 hold
        (_pct(2 * segment - fade_seconds), 1), (_pct(2 * segment), 0),  # fades out at the end of segment 1
        (_pct(total - fade_seconds), 0), (100.0, 1),  # fades back in at the end of segment 2 (loop point)
    ]
    overlay_stops = [
        (_pct(0), 0), (_pct(hold_seconds), 0),  # segment 0 hold
        (_pct(segment), 1),  # fades in at the end of segment 0
        (_pct(total - fade_seconds), 1), (100.0, 0),  # fades back out at the end of segment 2 (loop point)
    ]
    # Layer order matters: later layers paint on top in the composed SVG,
    # and the contour must stay visible over the MRSI overlay wherever
    # they overlap (frame 2's anat+contour+MRSI state) rather than being
    # occluded by it -- so overlay is added first, contour last.
    return compose_layered_crossfade_svg(
        anatomy_doc,
        [(overlay_doc, overlay_stops), (contour_doc, contour_stops)],
        out_path,
        flicker_id,
        total_seconds=total,
    )


def render_axial_before_after_svg_flicker(
    before: np.ndarray,
    after: np.ndarray,
    out_path: str | Path,
    flicker_id: str,
    cmap: str = "viridis",
    colorbar_label: str | None = None,
    n_slices: int = 10,
    spike_mask: np.ndarray | None = None,
) -> Path:
    """Hover-to-flicker counterpart of the MRSI Raw tab's single-row axial
    montage: ``before`` (e.g. raw, pre-spike-filter) and ``after`` (e.g.
    spike-filtered) are two full layers merged via
    :func:`compose_flicker_svg`, rather than one static background with a
    transparent overlay -- both layers show real anatomy here, so neither
    is naturally "the background".

    With ``spike_mask`` given, slices are chosen by where the flagged
    voxels actually are (:func:`axial_slice_indices_by_mask_count`),
    falling back to center-weighted indices (:func:`axial_slices_center_weighted`)
    to pad out to ``n_slices`` -- otherwise this montage could show spike
    repair's "before" and "after" at slices with no repaired voxels at all.
    Without a mask, slice indices fall back to ``after``'s own
    center-weighted indices, chosen rather than ``before``'s: an unfiltered
    acquisition spike can make a slice look nonempty by ``np.any(... > 0)``
    even where the real, post-filter signal is otherwise unremarkable, so
    anchoring to the filtered map keeps slice choice robust to spikes.
    Color scale is likewise shared from ``after``'s 99.5th percentile (see
    :mod:`mrsiprep.reports.mrsi_raw_overview`'s own rationale), so a single
    spike pixel in ``before`` can't wash out every panel.

    Each layer carries a "Raw (unfiltered)"/"Spike-filtered" badge on its
    first panel, so which state is currently showing is explicit rather
    than only inferable from remembering which way the hover flips.
    """
    import io

    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    before = np.squeeze(before)
    after = np.squeeze(after)

    if spike_mask is not None:
        indices = axial_slice_indices_by_mask_count(spike_mask, n_slices, fallback=after)
    else:
        indices = [index for index, _ in axial_slices_center_weighted(after, n_slices)]
    finite_after = after[np.isfinite(after)]
    vmax = float(np.percentile(finite_after, 99.5)) if finite_after.size else float(np.nanmax(after))
    vmin = 0.0
    vmax = max(vmax, vmin + 1e-6)

    n = len(indices)

    def _render(volume, *, state_label: str, state_color: str, draw_colorbar: bool, transparent: bool, fixed_positions: list | None):
        # Extra height (2.2 -> 3.0) plus an explicit constrained_layout pad
        # reserve real room for the state title above the per-panel "z="
        # titles -- at the original height the title either landed above
        # y=1 in figure coordinates and was clipped at the SVG canvas edge,
        # or (once the canvas was tall enough on its own) sat close enough
        # to the panel titles to visually collide with them in a browser's
        # <object> rendering, even though a standalone raster of the same
        # file looked fine (confirmed empirically both ways).
        fig, axes = plt.subplots(
            1, n, figsize=(1.8 * n, 3.0), constrained_layout=(fixed_positions is None),
        )
        if fixed_positions is None:
            fig.set_constrained_layout_pads(h_pad=0.35)
        if n == 1:
            axes = [axes]
        image = None
        for ax, index in zip(axes, indices):
            plane = np.rot90(np.take(volume, index, axis=2))
            image = ax.imshow(plane, cmap=cmap, vmin=vmin, vmax=vmax)
            ax.set_title(f"z={index}", fontsize=8)
            ax.axis("off")
        # Which state is currently showing must be readable without relying
        # on the viewer remembering which way the hover flips -- a large,
        # full-width title above the whole montage (not a small in-panel
        # badge, which was easy to miss next to ten slice panels), present
        # in both layers so it stays pinned at the same spot once merged,
        # just with different text/color. fig.suptitle (not an axes title)
        # so it reads as "the whole montage's state", not one panel's.
        fig.suptitle(state_label, fontsize=14, fontweight="bold", color=state_color, y=0.95)
        cbar = None
        if colorbar_label is not None and image is not None:
            # Reserve identical colorbar space in both layers (constrained_layout
            # reflows panel geometry based on what's actually drawn, so a
            # colorbar on only one layer desyncs the two documents' axes once
            # merged -- see render_triplanar_svg_flicker's own note on this),
            # but only the "before" (static) layer's colorbar stays visible;
            # the "after" (hover) layer's is hidden via alpha so the flicker
            # doesn't show a second colorbar fading in and out on top of it.
            # One shared colorbar (not one per layer) is correct here: before
            # and after are rendered with the same vmin/vmax, so a second
            # colorbar would be identical, not a different scale per state --
            # the label instead says explicitly that it covers both.
            cbar = fig.colorbar(image, ax=axes, fraction=0.02, pad=0.02, label=f"{colorbar_label} (both states)")
            if not draw_colorbar:
                for artist in (cbar.ax.yaxis.label, cbar.outline, *cbar.ax.get_yticklabels(), *cbar.ax.yaxis.get_ticklines()):
                    artist.set_alpha(0)
                if cbar.ax.images:
                    cbar.ax.images[0].set_alpha(0)
        # The colorbar's own axes must be pinned too, not just the slice
        # panels: fig.colorbar() on an unconstrained second pass places it
        # wherever matplotlib's default layout puts it, which is NOT where
        # constrained_layout placed it on the first (background) pass --
        # confirmed empirically, the foreground colorbar landed on top of
        # the last slice panel instead of in its own reserved column.
        pinned_axes = [*axes, cbar.ax] if cbar is not None else list(axes)
        if fixed_positions is None:
            fig.canvas.draw()
            positions = [ax.get_position().frozen() for ax in pinned_axes]
        else:
            for ax, pos in zip(pinned_axes, fixed_positions):
                ax.set_position(pos)
            positions = fixed_positions
        buf = io.BytesIO()
        fig.savefig(buf, format="svg", transparent=transparent)
        plt.close(fig)
        return buf.getvalue().decode(), positions

    # Unlike the T1w/MNI alignment flicker (a sparse metabolite overlay on a
    # full-head background, genuinely meant to stay transparent so the
    # background shows through the overlay's empty space), both layers here
    # are full, opaque anatomical montages covering their entire panels.
    # The foreground must therefore be rendered opaque too (transparent=False):
    # with a transparent background, matplotlib's SVG has no opaque rect
    # behind the image/text, so at rest -- both layers sitting at
    # opacity:1 until the hover animation fades the foreground out -- the
    # background layer's own titles and colorbar show straight through,
    # producing overlapping, unreadable double text (confirmed empirically).
    # Opaque white here means the CSS fade genuinely swaps one clean view
    # for the other instead of blending two half-visible ones.
    before_doc, positions = _render(
        before, state_label="Raw (unfiltered)", state_color="#b3432b", draw_colorbar=True, transparent=False, fixed_positions=None
    )
    after_doc, _ = _render(
        after, state_label="Spike-filtered", state_color="#2f5d50", draw_colorbar=False, transparent=False, fixed_positions=positions
    )
    return compose_flicker_svg(before_doc, after_doc, out_path, flicker_id)


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

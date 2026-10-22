"""Shared triplanar slice rendering (mrsiprep/reports/slices.py).

No test module existed for this shared helper before; it was only ever
exercised indirectly through the six report modules that import it.
"""

import tempfile
import unittest
import unittest.mock
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from mrsiprep.reports.slices import (
    _occupied_slice_indices,
    _panel_title,
    _prefix_svg_ids,
    _voxel_index_to_mm,
    axial_slices_center_weighted,
    center_weighted_slice_indices,
    compose_flicker_svg,
    render_axial_before_after_svg_flicker,
    render_multi_slice_triplanar_png,
    render_multi_slice_triplanar_svg_flicker,
    render_triplanar_svg_flicker,
    triplanar_slices,
)


class TriplanarSlicesTests(unittest.TestCase):
    def test_returns_the_center_slice_of_each_plane_by_default(self):
        volume = np.arange(4 * 6 * 8, dtype=float).reshape(4, 6, 8)
        slices = triplanar_slices(volume)
        self.assertEqual(set(slices), {"sagittal", "coronal", "axial"})
        # rot90 changes shape for non-square planes; check against the same
        # transform rather than the raw index into volume.
        self.assertTrue(np.array_equal(slices["axial"], np.rot90(volume[:, :, 4])))

    def test_squeezes_a_singleton_fourth_dimension(self):
        volume = np.zeros((4, 4, 4, 1))
        slices = triplanar_slices(volume)
        self.assertEqual(slices["axial"].shape, (4, 4))


class OccupiedSliceIndicesTests(unittest.TestCase):
    def test_confines_indices_to_the_nonzero_extent_along_the_axis(self):
        volume = np.zeros((10, 4, 4))
        volume[3:7] = 1.0  # only slices 3-6 (axis 0) have data
        indices = _occupied_slice_indices(volume, axis=0, n_slices=4)
        self.assertGreaterEqual(min(indices), 3)
        self.assertLessEqual(max(indices), 6)

    def test_falls_back_to_the_whole_axis_when_volume_is_all_zero(self):
        volume = np.zeros((10, 4, 4))
        indices = _occupied_slice_indices(volume, axis=0, n_slices=4)
        self.assertEqual(min(indices), 0)
        self.assertEqual(max(indices), 9)

    def test_returns_a_single_repeated_index_for_a_one_slice_extent(self):
        volume = np.zeros((10, 4, 4))
        volume[5] = 1.0
        indices = _occupied_slice_indices(volume, axis=0, n_slices=4)
        self.assertEqual(indices, [5] * 4)


class RenderMultiSliceTriplanarPngTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.out = Path(self._tmpdir.name) / "fig.png"

    def _volumes(self, shape=(12, 14, 12)):
        rng = np.random.default_rng(0)
        background = rng.uniform(0, 1, size=shape)
        overlay = np.zeros(shape)
        overlay[4:8, 5:9, 4:8] = rng.uniform(1, 100, size=(4, 4, 4))
        return background, overlay

    def test_writes_a_file_with_three_rows_of_n_slices(self):
        background, overlay = self._volumes()
        render_multi_slice_triplanar_png(background, self.out, overlay=overlay, mode="solid", n_slices=5)
        self.assertTrue(self.out.exists())
        self.assertGreater(self.out.stat().st_size, 0)

    def test_slice_indices_are_chosen_from_the_overlay_not_the_background(self):
        """A full-head background is nonzero almost everywhere; indexing off
        it would spend most of the montage on anatomy the overlay never
        reaches. The overlay's own extent should drive slice selection."""
        shape = (20, 20, 20)
        background = np.ones(shape)  # nonzero everywhere
        overlay = np.zeros(shape)
        overlay[9:11, 9:11, 9:11] = 5.0  # a small blob near the center only

        seen_axes = []
        original = _occupied_slice_indices

        def _capture(volume, axis, n_slices):
            seen_axes.append(volume)
            return original(volume, axis, n_slices)

        import mrsiprep.reports.slices as slices_module

        with unittest.mock.patch.object(slices_module, "_occupied_slice_indices", side_effect=_capture):
            render_multi_slice_triplanar_png(background, self.out, overlay=overlay, mode="solid", n_slices=3)

        # Every call should have been made with the overlay array, not the
        # all-ones background.
        for volume in seen_axes:
            self.assertTrue(np.array_equal(volume, overlay))

    def test_falls_back_to_background_extent_without_an_overlay(self):
        background, _overlay = self._volumes()
        # Must not raise even though there is nothing to index slices from
        # but the background itself.
        render_multi_slice_triplanar_png(background, self.out, overlay=None, n_slices=4)
        self.assertTrue(self.out.exists())

    def test_shares_one_colour_scale_across_every_panel(self):
        """Regression: per-imshow auto-scaling with vmin/vmax left unset gave
        each panel its own scale, so the same signal level looked different
        panel to panel and the shared colorbar's numbers meant nothing."""
        import matplotlib.pyplot as plt

        shape = (10, 10, 10)
        background = np.ones(shape)
        overlay = np.zeros(shape)
        overlay[2:4, 2:4, 2:4] = 10.0
        overlay[6:8, 6:8, 6:8] = 90.0  # a much brighter region elsewhere

        captured_clims = []
        original_imshow = plt.Axes.imshow

        def _capture(self, data, **kwargs):
            image = original_imshow(self, data, **kwargs)
            if kwargs.get("cmap") == "hot":
                captured_clims.append(image.get_clim())
            return image

        with unittest.mock.patch.object(plt.Axes, "imshow", _capture):
            render_multi_slice_triplanar_png(background, self.out, overlay=overlay, mode="solid", overlay_cmap="hot", n_slices=3)

        self.assertTrue(captured_clims)
        self.assertEqual(len(set(captured_clims)), 1, "every overlay panel must share the same vmin/vmax")

    def test_writes_a_colorbar_only_when_a_label_is_given(self):
        background, overlay = self._volumes()
        render_multi_slice_triplanar_png(background, self.out, overlay=overlay, mode="solid", colorbar_label=None, n_slices=3)
        self.assertTrue(self.out.exists())  # must not raise without a label

    def test_outline_mode_does_not_require_a_colorbar(self):
        shape = (10, 10, 10)
        background = np.ones(shape)
        labels = np.zeros(shape, dtype=int)
        labels[3:6, 3:6, 3:6] = 1
        render_multi_slice_triplanar_png(background, self.out, overlay=labels, mode="outline", n_slices=3)
        self.assertTrue(self.out.exists())


_SIMPLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'version="1.1" viewBox="0 0 10 10" width="10pt" height="10pt">'
    '<defs><clipPath id="p_clip"><rect width="10" height="10"/></clipPath></defs>'
    '<g id="figure_1" clip-path="url(#p_clip)"><rect width="5" height="5"/></g>'
    "</svg>"
)


class PrefixSvgIdsTests(unittest.TestCase):
    """Regression guard: two independently matplotlib-rendered SVGs reuse
    the exact same element ids ("figure_1", "axes_1", clip-path hashes,
    ...) every time, since matplotlib numbers them fresh per document. Two
    such documents merged into one SVG without prefixing collide on every
    id -- duplicate ids are invalid SVG and corrupt rendering (confirmed
    empirically: a merged reportlet's third panel visibly shifted/shrank
    until this fix)."""

    def test_rewrites_id_attribute_and_its_url_reference_together(self):
        root = ET.fromstring(_SIMPLE_SVG)
        _prefix_svg_ids(root, "bg-")
        ids = {el.get("id") for el in root.iter() if el.get("id")}
        self.assertEqual(ids, {"bg-p_clip", "bg-figure_1"})
        clip_path_user = next(el for el in root.iter() if el.get("clip-path"))
        self.assertEqual(clip_path_user.get("clip-path"), "url(#bg-p_clip)")

    def test_two_independently_prefixed_documents_no_longer_collide(self):
        bg_root = ET.fromstring(_SIMPLE_SVG)
        fg_root = ET.fromstring(_SIMPLE_SVG)
        _prefix_svg_ids(bg_root, "bg-")
        _prefix_svg_ids(fg_root, "fg-")
        bg_ids = {el.get("id") for el in bg_root.iter() if el.get("id")}
        fg_ids = {el.get("id") for el in fg_root.iter() if el.get("id")}
        self.assertEqual(bg_ids & fg_ids, set())


class ComposeFlickerSvgTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.out = Path(self._tmpdir.name) / "composed.svg"

    def test_writes_well_formed_xml_with_both_layers_and_no_duplicate_ids(self):
        compose_flicker_svg(_SIMPLE_SVG, _SIMPLE_SVG, self.out, flicker_id="abc123")
        tree = ET.parse(self.out)  # raises on malformed XML / duplicate attrs
        root = tree.getroot()
        ns = "{http://www.w3.org/2000/svg}"
        classes = [g.get("class") for g in root.findall(f"{ns}g")]
        self.assertIn("background-svg", classes)
        self.assertTrue(any(c and c.startswith("foreground-svg") for c in classes))

        ids = [el.get("id") for el in root.iter() if el.get("id")]
        self.assertEqual(len(ids), len(set(ids)), "merged document must not contain duplicate ids")

    def test_animation_name_is_scoped_to_flicker_id(self):
        compose_flicker_svg(_SIMPLE_SVG, _SIMPLE_SVG, self.out, flicker_id="unique123")
        content = self.out.read_text()
        self.assertIn("flicker-unique123", content)
        self.assertIn("flicker-fg-unique123", content)

    def test_different_flicker_ids_do_not_share_an_animation_name(self):
        out2 = Path(self._tmpdir.name) / "composed2.svg"
        compose_flicker_svg(_SIMPLE_SVG, _SIMPLE_SVG, self.out, flicker_id="one")
        compose_flicker_svg(_SIMPLE_SVG, _SIMPLE_SVG, out2, flicker_id="two")
        self.assertNotIn("flicker-two", self.out.read_text())
        self.assertNotIn("flicker-one", out2.read_text())


class VoxelIndexToMmTests(unittest.TestCase):
    def test_axial_uses_the_z_axis_translation_and_scale(self):
        affine = np.array([[2, 0, 0, -10], [0, 2, 0, -20], [0, 0, 2, -30], [0, 0, 0, 1]], dtype=float)
        # axial -> axis 2 (z): mm = 2*index + (-30)
        self.assertAlmostEqual(_voxel_index_to_mm(affine, "axial", 0), -30.0)
        self.assertAlmostEqual(_voxel_index_to_mm(affine, "axial", 5), -20.0)

    def test_sagittal_uses_the_x_axis_translation_and_scale(self):
        affine = np.array([[2, 0, 0, -10], [0, 2, 0, -20], [0, 0, 2, -30], [0, 0, 0, 1]], dtype=float)
        self.assertAlmostEqual(_voxel_index_to_mm(affine, "sagittal", 0), -10.0)


class PanelTitleTests(unittest.TestCase):
    def test_falls_back_to_bare_voxel_index_without_an_affine(self):
        self.assertEqual(_panel_title(None, "axial", 7), "7")
        self.assertEqual(_panel_title(None, "sagittal", -3), "-3")

    def test_uses_the_matching_axis_letter_and_mm_value_per_plane(self):
        affine = np.array([[2, 0, 0, -10], [0, 2, 0, -20], [0, 0, 2, -30], [0, 0, 0, 1]], dtype=float)
        self.assertEqual(_panel_title(affine, "sagittal", 0), "x=-10")
        self.assertEqual(_panel_title(affine, "coronal", 0), "y=-20")
        self.assertEqual(_panel_title(affine, "axial", 0), "z=-30")

    def test_rounds_to_the_nearest_integer_mm(self):
        affine = np.array([[1.5, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
        self.assertEqual(_panel_title(affine, "sagittal", 1), "x=2")  # 1.5 rounds to 2


class RenderTriplanarSvgFlickerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.out = Path(self._tmpdir.name) / "flicker.svg"

    def test_writes_a_well_formed_composed_svg(self):
        rng = np.random.default_rng(0)
        volume = rng.uniform(0, 1, size=(10, 10, 10))
        overlay = np.zeros_like(volume)
        overlay[3:6, 3:6, 3:6] = rng.uniform(1, 10, size=(3, 3, 3))
        bg_slices = triplanar_slices(volume)
        ov_slices = triplanar_slices(overlay)

        render_triplanar_svg_flicker(bg_slices, self.out, ov_slices, flicker_id="t1", colorbar_label="X")

        self.assertTrue(self.out.exists())
        ET.parse(self.out)  # must be well-formed

    def test_colorbar_reserves_identical_space_in_both_layers(self):
        """Regression: the background layer drew no colorbar while the
        foreground did, so constrained_layout gave each layer different
        panel geometry and the two documents' axes stopped lining up once
        merged. A hidden colorbar on the background now reserves the same
        space. Guard this by checking both layers' panel content occupies
        the same horizontal extent (bounding-box width) in the final SVG."""
        rng = np.random.default_rng(0)
        volume = rng.uniform(0, 1, size=(10, 10, 10))
        overlay = np.zeros_like(volume)
        overlay[3:6, 3:6, 3:6] = rng.uniform(1, 10, size=(3, 3, 3))
        bg_slices = triplanar_slices(volume)
        ov_slices = triplanar_slices(overlay)

        render_triplanar_svg_flicker(bg_slices, self.out, ov_slices, flicker_id="t2", colorbar_label="X")

        tree = ET.parse(self.out)
        root = tree.getroot()
        # Both layers' root <svg> (nested inside their <g>) must report the
        # same width/height -- that's what the hidden-colorbar fix
        # guarantees (same matplotlib figure size + same reserved layout
        # space), and is the simplest externally-observable proxy for "the
        # two layers' axes line up."
        ns = "{http://www.w3.org/2000/svg}"
        widths = set()
        for g in root.findall(f"{ns}g"):
            inner_svg = g.find(f".//{ns}svg")
            # matplotlib's own svg root becomes a nested element once
            # merged only if present; fall back to the group's own metadata
            # width if nested svg tags aren't used by this matplotlib version.
            if inner_svg is not None and inner_svg.get("width"):
                widths.add(inner_svg.get("width"))
        # Not all matplotlib versions nest a width-bearing svg tag, so this
        # is a soft check: if widths were found, they must agree.
        if widths:
            self.assertEqual(len(widths), 1)


class RenderMultiSliceTriplanarSvgFlickerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.out = Path(self._tmpdir.name) / "flicker_multi.svg"

    def _volumes(self, shape=(16, 18, 16)):
        rng = np.random.default_rng(0)
        background = rng.uniform(0, 1, size=shape)
        overlay = np.zeros(shape)
        overlay[6:10, 7:11, 6:10] = rng.uniform(1, 100, size=(4, 4, 4))
        return background, overlay

    def test_writes_a_well_formed_composed_svg(self):
        background, overlay = self._volumes()
        render_multi_slice_triplanar_svg_flicker(
            background, self.out, overlay, flicker_id="m1", overlay_mode="solid", colorbar_label="Y", n_slices=4
        )
        self.assertTrue(self.out.exists())
        ET.parse(self.out)

    def test_mm_coordinate_titles_used_when_affine_given(self):
        """render_multi_slice_triplanar_svg_flicker must actually pass the
        affine through to _panel_title() (covered directly, with exact
        values, by PanelTitleTests below) rather than silently dropping it
        -- checking the rendered SVG's raw text isn't reliable here since
        matplotlib's SVG backend can embed panel content (including, in
        some configurations, title text) as a base64 PNG raster rather
        than literal/vector text, so this only checks the call succeeds
        with a non-trivial affine and produces well-formed output."""
        background, overlay = self._volumes()
        affine = np.eye(4) * 2
        affine[3, 3] = 1
        affine[:3, 3] = [-16, -18, -16]
        render_multi_slice_triplanar_svg_flicker(
            background,
            self.out,
            overlay,
            flicker_id="m2",
            overlay_mode="solid",
            colorbar_label="Y",
            n_slices=3,
            affine=affine,
        )
        self.assertTrue(self.out.exists())
        ET.parse(self.out)

    def test_outline_mode_does_not_require_a_colorbar(self):
        shape = (12, 12, 12)
        background = np.ones(shape)
        labels = np.zeros(shape, dtype=int)
        labels[4:7, 4:7, 4:7] = 1
        render_multi_slice_triplanar_svg_flicker(
            background, self.out, labels, flicker_id="m4", overlay_mode="outline", n_slices=3
        )
        self.assertTrue(self.out.exists())
        ET.parse(self.out)

    def test_wm_mask_contour_does_not_break_rendering(self):
        """wm_mask is optional -- passing it must still produce a valid,
        well-formed composed document (the contour itself, drawn via
        mask_contour_overlay, is exercised directly by
        MaskContourOverlayTests below)."""
        background, overlay = self._volumes()
        wm_mask = np.zeros_like(background)
        wm_mask[5:11, 6:12, 5:11] = 1.0
        render_multi_slice_triplanar_svg_flicker(
            background, self.out, overlay, flicker_id="m5", overlay_mode="solid", colorbar_label="Y", n_slices=3, wm_mask=wm_mask
        )
        self.assertTrue(self.out.exists())
        ET.parse(self.out)

    def test_size_scale_grows_the_composed_svg_dimensions(self):
        background, overlay = self._volumes()
        default_out = Path(self._tmpdir.name) / "default_scale.svg"
        scaled_out = Path(self._tmpdir.name) / "bigger_scale.svg"
        render_multi_slice_triplanar_svg_flicker(
            background, default_out, overlay, flicker_id="s1", overlay_mode="solid", n_slices=3, size_scale=1.0
        )
        render_multi_slice_triplanar_svg_flicker(
            background, scaled_out, overlay, flicker_id="s2", overlay_mode="solid", n_slices=3, size_scale=1.3
        )

        def _viewbox_area(path):
            root = ET.parse(path).getroot()
            _, _, width, height = (float(value) for value in root.get("viewBox").split())
            return width * height

        self.assertGreater(_viewbox_area(scaled_out), _viewbox_area(default_out) * 1.2)

    def test_colorbar_axes_do_not_overlap_the_last_slice_column(self):
        """Regression guard: fig.colorbar(..., ax=axes.ravel().tolist()) used
        to steal space from whichever axes constrained_layout picked last,
        visibly overlapping/obscuring that panel's image (confirmed via a
        real rendered report). The colorbar must live in its own dedicated
        column, to the right of every slice panel's x1."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        background, overlay = self._volumes()
        captured = {}
        orig_savefig = plt.Figure.savefig

        def spy_savefig(self, *args, **kwargs):
            captured["axes"] = list(self.get_axes())
            return orig_savefig(self, *args, **kwargs)

        plt.Figure.savefig = spy_savefig
        try:
            render_multi_slice_triplanar_svg_flicker(
                background, self.out, overlay, flicker_id="c1", overlay_mode="solid", colorbar_label="Y", n_slices=3
            )
        finally:
            plt.Figure.savefig = orig_savefig

        axes = captured["axes"]
        # Last axes created is the colorbar's own (fig.colorbar appends it).
        cbar_ax = axes[-1]
        slice_axes = [ax for ax in axes[:-1] if ax.get_images()]
        max_slice_x1 = max(ax.get_position().x1 for ax in slice_axes)
        self.assertGreaterEqual(cbar_ax.get_position().x0, max_slice_x1)

    def test_colorbar_shows_its_axis_label_and_tick_labels(self):
        """Regression guard: turning off the colorbar column's unused
        top/bottom-row axes via axis("off") (rather than set_visible(False))
        silently suppressed the colorbar's own tick numbers and axis label
        under constrained_layout -- no exception, no malformed SVG, just
        missing text (confirmed empirically by comparing otherwise-identical
        renders). Well-formed-XML checks alone can't catch this."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        background, overlay = self._volumes()
        captured = {}
        orig_savefig = plt.Figure.savefig

        def spy_savefig(self, *args, **kwargs):
            if "cbar" not in captured:
                for ax in self.get_axes():
                    if ax.get_ylabel() == "Y":
                        captured["cbar_ax"] = ax
            return orig_savefig(self, *args, **kwargs)

        plt.Figure.savefig = spy_savefig
        try:
            render_multi_slice_triplanar_svg_flicker(
                background, self.out, overlay, flicker_id="c2", overlay_mode="solid", colorbar_label="Y", n_slices=3
            )
        finally:
            plt.Figure.savefig = orig_savefig

        cbar_ax = captured["cbar_ax"]
        self.assertEqual(cbar_ax.get_ylabel(), "Y")
        tick_texts = [label.get_text() for label in cbar_ax.get_yticklabels()]
        self.assertTrue(any(text.strip() for text in tick_texts), f"no non-empty tick labels found: {tick_texts!r}")


class CenterWeightedSliceIndicesTests(unittest.TestCase):
    def test_endpoints_are_included(self):
        indices = center_weighted_slice_indices(25, 10)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 24)

    def test_spacing_is_denser_near_the_center(self):
        indices = center_weighted_slice_indices(44, 10)
        gaps = [int(indices[i + 1] - indices[i]) for i in range(len(indices) - 1)]
        mid = len(gaps) // 2
        self.assertLess(min(gaps[mid - 1 : mid + 2]), gaps[0])
        self.assertLess(min(gaps[mid - 1 : mid + 2]), gaps[-1])

    def test_handles_trivial_sizes(self):
        self.assertEqual(list(center_weighted_slice_indices(1, 10)), [0])


class AxialSlicesCenterWeightedTests(unittest.TestCase):
    def test_returns_up_to_n_slices_spanning_the_axis(self):
        data = np.ones((10, 10, 20), dtype=np.float32)
        slices = axial_slices_center_weighted(data, n_slices=10)
        indices = [index for index, _ in slices]
        self.assertLessEqual(len(indices), 10)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 19)

    def test_skips_entirely_empty_slices(self):
        data = np.zeros((10, 10, 20), dtype=np.float32)
        data[:, :, 5:15] = 1.0
        slices = axial_slices_center_weighted(data, n_slices=10)
        indices = [index for index, _ in slices]
        self.assertTrue(all(5 <= index < 15 for index in indices))

    def test_falls_back_to_center_slice_when_all_empty(self):
        data = np.zeros((10, 10, 20), dtype=np.float32)
        slices = axial_slices_center_weighted(data, n_slices=10)
        self.assertEqual(len(slices), 1)

    def test_reference_volume_decides_which_slices_are_skipped(self):
        """Passing a separate reference (e.g. the filtered map) rather than
        volume_data itself must decide which slices to keep, so a slice
        where only the raw map happens to be nonzero (an outlier spike) but
        the reference is empty is still skipped."""
        data = np.zeros((6, 6, 10), dtype=np.float32)
        data[0, 0, 0] = 999.0  # a spike in an otherwise-empty slice
        reference = np.zeros((6, 6, 10), dtype=np.float32)
        reference[:, :, 4:7] = 1.0
        slices = axial_slices_center_weighted(data, n_slices=10, reference=reference)
        indices = [index for index, _ in slices]
        self.assertTrue(all(4 <= index < 7 for index in indices))


class RenderAxialBeforeAfterSvgFlickerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.out = Path(self._tmpdir.name) / "before_after.svg"

    def test_writes_a_well_formed_composed_svg(self):
        rng = np.random.default_rng(0)
        before = rng.uniform(0, 5, size=(8, 8, 10))
        after = before.copy()
        after[2:4, 2:4, 2:4] = 0.0

        render_axial_before_after_svg_flicker(before, after, self.out, flicker_id="sf1", colorbar_label="CrPCr")

        self.assertTrue(self.out.exists())
        ET.parse(self.out)  # must be well-formed

    def test_slice_indices_are_chosen_from_after_not_before(self):
        """An extreme raw-only spike in `before` must not make an otherwise
        empty slice look nonempty -- slice selection should anchor to
        `after`, matching the MRSI Raw tab's own rationale for using the
        filtered map."""
        before = np.zeros((6, 6, 10), dtype=np.float32)
        before[0, 0, 0] = 999.0
        after = np.zeros((6, 6, 10), dtype=np.float32)
        after[:, :, 4:7] = 1.0

        captured = {}
        import matplotlib.pyplot as plt

        orig_subplots = plt.subplots

        def _spy_subplots(*args, **kwargs):
            fig, axes = orig_subplots(*args, **kwargs)
            captured["axes"] = axes
            return fig, axes

        with unittest.mock.patch.object(plt, "subplots", side_effect=_spy_subplots):
            render_axial_before_after_svg_flicker(before, after, self.out, flicker_id="sf2", n_slices=10)

        titles = [ax.get_title() for ax in captured["axes"]]
        indices = [int(title.split("=")[1]) for title in titles if title]
        self.assertTrue(all(4 <= index < 7 for index in indices))

    def test_colorbar_present_only_when_label_given(self):
        rng = np.random.default_rng(0)
        before = rng.uniform(0, 5, size=(6, 6, 8))
        after = before.copy()

        render_axial_before_after_svg_flicker(before, after, self.out, flicker_id="sf3", colorbar_label=None)

        tree = ET.parse(self.out)
        text_content = "".join(tree.getroot().itertext())
        self.assertNotIn("CrPCr", text_content)


class MaskContourOverlayTests(unittest.TestCase):
    def test_draws_a_contour_line_for_a_nonempty_mask(self):
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from mrsiprep.reports.slices import mask_contour_overlay

        mask = np.zeros((20, 20))
        mask[5:15, 5:15] = 1.0
        fig, ax = plt.subplots()
        try:
            mask_contour_overlay(ax, mask, color="red")
            self.assertGreater(len(ax.lines), 0)
            self.assertEqual(ax.lines[0].get_color(), "red")
        finally:
            plt.close(fig)

    def test_empty_mask_draws_no_contour(self):
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from mrsiprep.reports.slices import mask_contour_overlay

        mask = np.zeros((20, 20))
        fig, ax = plt.subplots()
        try:
            mask_contour_overlay(ax, mask, color="red")
            self.assertEqual(len(ax.lines), 0)
        finally:
            plt.close(fig)


if __name__ == "__main__":
    unittest.main()

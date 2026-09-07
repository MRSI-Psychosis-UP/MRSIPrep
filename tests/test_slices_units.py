"""Shared triplanar slice rendering (mrsiprep/reports/slices.py).

No test module existed for this shared helper before; it was only ever
exercised indirectly through the six report modules that import it.
"""

import tempfile
import unittest
import unittest.mock
from pathlib import Path

import numpy as np

from mrsiprep.reports.slices import (
    _occupied_slice_indices,
    render_multi_slice_triplanar_png,
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


if __name__ == "__main__":
    unittest.main()

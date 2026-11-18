import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.mrsi.filtering import (
    _inpaint_voxels_with_median,
    _median_exclude_center,
    biharmonic_repair,
    default_spike_max_cluster_voxels,
    filter_metabolite_maps,
)


class DefaultSpikeMaxClusterVoxelsTests(unittest.TestCase):
    def test_3t_like_voxel_size_returns_six(self):
        self.assertEqual(default_spike_max_cluster_voxels((5.0, 5.0, 5.3)), 6)

    def test_7t_like_voxel_size_returns_nine(self):
        self.assertEqual(default_spike_max_cluster_voxels((3.4, 3.4, 3.4)), 9)

    def test_picks_nearer_regime_by_volume_proximity(self):
        # Volume roughly halfway between the two regimes' native volumes
        # (3T ~125 mm^3, 7T ~39.3 mm^3): a cube just above the midpoint
        # volume should round to the 3T (6) bucket.
        midpoint_volume = (5.0**3 + 3.4**3) / 2
        side = midpoint_volume ** (1 / 3)
        self.assertEqual(default_spike_max_cluster_voxels((side + 0.05, side + 0.05, side + 0.05)), 6)
        self.assertEqual(default_spike_max_cluster_voxels((side - 0.05, side - 0.05, side - 0.05)), 9)


class MedianExcludeCenterTests(unittest.TestCase):
    def test_excludes_the_middle_element(self):
        # 27 values for a 3x3x3 neighborhood; center (index 13) is an outlier
        # that must not influence the result.
        values = np.arange(27, dtype=np.float64)
        values[13] = 1000.0
        result = _median_exclude_center(values)
        expected = np.median(np.concatenate([values[:13], values[14:]]))
        self.assertEqual(result, expected)


class InpaintVoxelsWithMedianTests(unittest.TestCase):
    def test_no_op_when_mask_is_empty(self):
        image = np.random.default_rng(0).random((6, 6, 6)).astype(np.float32)
        mask = np.zeros_like(image, dtype=bool)
        result = _inpaint_voxels_with_median(image, mask)
        np.testing.assert_array_equal(result, image)
        self.assertIsNot(result, image)  # a copy, not the same array

    def test_masked_voxel_is_replaced_by_neighborhood_median(self):
        image = np.ones((5, 5, 5), dtype=np.float32)
        image[2, 2, 2] = 999.0  # a spike
        mask = np.zeros_like(image, dtype=bool)
        mask[2, 2, 2] = True
        result = _inpaint_voxels_with_median(image, mask)
        self.assertEqual(result[2, 2, 2], 1.0)  # surrounded entirely by 1.0

    def test_unmasked_voxels_are_untouched(self):
        rng = np.random.default_rng(1)
        image = rng.random((5, 5, 5)).astype(np.float32)
        mask = np.zeros_like(image, dtype=bool)
        mask[2, 2, 2] = True
        result = _inpaint_voxels_with_median(image, mask)
        untouched = ~mask
        np.testing.assert_array_equal(result[untouched], image[untouched])


class BiharmonicRepairTests(unittest.TestCase):
    def _header_and_affine(self, zooms=(5.0, 5.0, 5.0)):
        img = nib.Nifti1Image(np.zeros((8, 8, 8), dtype=np.float32), np.eye(4))
        img.header.set_zooms(zooms)
        return img.header, img.affine

    def test_spike_voxel_no_longer_matches_its_original_extreme_value(self):
        data = np.ones((10, 10, 10), dtype=np.float32)
        data[5, 5, 5] = 999.0
        brain = np.ones((10, 10, 10), dtype=bool)
        spike_mask = np.zeros((10, 10, 10), dtype=bool)
        spike_mask[5, 5, 5] = True
        header, affine = self._header_and_affine()

        repaired, missing = biharmonic_repair(data, brain, spike_mask, header, affine, fwhm_mm=2.0)

        self.assertLess(repaired[5, 5, 5], 100.0)
        self.assertFalse(missing[5, 5, 5])  # median-repaired to nonzero, never reached the inpaint stage

    def test_voxels_outside_brain_are_zeroed(self):
        data = np.ones((10, 10, 10), dtype=np.float32)
        brain = np.zeros((10, 10, 10), dtype=bool)
        brain[2:8, 2:8, 2:8] = True
        spike_mask = np.zeros((10, 10, 10), dtype=bool)
        header, affine = self._header_and_affine()

        repaired, _ = biharmonic_repair(data, brain, spike_mask, header, affine, fwhm_mm=2.0)

        self.assertTrue(np.all(repaired[~brain] == 0))

    def test_missing_voxels_get_biharmonic_inpainted(self):
        data = np.ones((10, 10, 10), dtype=np.float32) * 5.0
        data[5, 5, 5] = 0.0  # a genuine hole, not a spike
        brain = np.ones((10, 10, 10), dtype=bool)
        spike_mask = np.zeros((10, 10, 10), dtype=bool)
        header, affine = self._header_and_affine()

        repaired, missing = biharmonic_repair(data, brain, spike_mask, header, affine, fwhm_mm=2.0)

        self.assertTrue(missing[5, 5, 5])
        self.assertGreater(repaired[5, 5, 5], 0.0)  # filled in, not left at zero

    def test_fwhm_defaults_to_voxel_size_derived_value_when_unset(self):
        data = np.ones((10, 10, 10), dtype=np.float32)
        data[5, 5, 5] = 50.0
        brain = np.ones((10, 10, 10), dtype=bool)
        spike_mask = np.zeros((10, 10, 10), dtype=bool)
        spike_mask[5, 5, 5] = True
        header, affine = self._header_and_affine(zooms=(5.0, 5.0, 5.0))

        # Must not raise despite fwhm_mm=None -- exercises the
        # header.get_zooms()-derived fallback (5.0 * sqrt(2) ~= 7).
        repaired, _ = biharmonic_repair(data, brain, spike_mask, header, affine, fwhm_mm=None)
        self.assertEqual(repaired.shape, data.shape)


class FilterMetaboliteMapsFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.brainmask_path = self.tmp / "brainmask.nii.gz"
        nib.save(nib.Nifti1Image(np.ones((6, 6, 6), dtype=np.float32), np.eye(4)), self.brainmask_path)
        self.met_path = self.tmp / "CrPCr.nii.gz"
        nib.save(nib.Nifti1Image(np.ones((6, 6, 6), dtype=np.float32), np.eye(4)), self.met_path)
        self.config = SimpleNamespace(
            filter_biharmonic=True,
            derivative_dir=self.tmp / "derivatives",
            overwrite_filt=False,
            overwrite=False,
            spike_max_cluster_voxels=None,
            spike_percentile=99.0,
            spike_extreme_zscore=4.0,
            filter_fwhm_mm=None,
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def _signal_out_path(self):
        return self.tmp / "mrsi" / "orig" / "sub-01_space-MRSI_met-CrPCr_desc-signalspikefilt_mrsi.nii.gz"

    def _mask_out_path(self):
        return self.tmp / "mrsi" / "orig" / "sub-01_space-MRSI_met-CrPCr_desc-spikemask_mask.nii.gz"


class DisabledFilterTests(FilterMetaboliteMapsFixture):
    def test_disabled_filter_returns_input_unchanged_without_touching_disk(self):
        self.config.filter_biharmonic = False
        with patch("mrsiprep.mrsi.filtering.load_3d_data") as load:
            result = filter_metabolite_maps(self.config, "01", "01", {"CrPCr": self.met_path}, self.brainmask_path)
        load.assert_not_called()
        self.assertEqual(result, {"CrPCr": self.met_path})


class CachedOutputTests(FilterMetaboliteMapsFixture):
    def test_existing_output_is_reused_without_recomputation(self):
        out = self._signal_out_path()
        out.parent.mkdir(parents=True)
        out.touch()
        with patch("mrsiprep.mrsi.filtering.mrsi_derivative", return_value=out), patch(
            "mrsiprep.mrsi.filtering.get_spike_mask"
        ) as get_spike_mask_mock:
            result = filter_metabolite_maps(self.config, "01", "01", {"CrPCr": self.met_path}, self.brainmask_path)
        get_spike_mask_mock.assert_not_called()
        self.assertEqual(result, {"CrPCr": out})

    def test_overwrite_flag_forces_recomputation_even_if_cached(self):
        out = self._signal_out_path()
        out.parent.mkdir(parents=True)
        out.touch()
        self.config.overwrite = True
        mask_out = self._mask_out_path()

        with patch("mrsiprep.mrsi.filtering.mrsi_derivative", side_effect=[out, mask_out]), patch(
            "mrsiprep.mrsi.filtering.get_spike_mask", return_value=np.zeros((6, 6, 6), dtype=bool)
        ) as get_spike_mask_mock, patch(
            "mrsiprep.mrsi.filtering.biharmonic_repair", return_value=(np.ones((6, 6, 6), dtype=np.float32), np.zeros((6, 6, 6), dtype=bool))
        ):
            filter_metabolite_maps(self.config, "01", "01", {"CrPCr": self.met_path}, self.brainmask_path)

        get_spike_mask_mock.assert_called_once()


class ComputePathTests(FilterMetaboliteMapsFixture):
    def test_resolves_max_cluster_from_voxel_size_when_unset(self):
        out = self._signal_out_path()
        mask_out = self._mask_out_path()
        with patch("mrsiprep.mrsi.filtering.mrsi_derivative", side_effect=[out, mask_out]), patch(
            "mrsiprep.mrsi.filtering.get_spike_mask", return_value=np.zeros((6, 6, 6), dtype=bool)
        ) as get_spike_mask_mock, patch(
            "mrsiprep.mrsi.filtering.biharmonic_repair", return_value=(np.ones((6, 6, 6), dtype=np.float32), np.zeros((6, 6, 6), dtype=bool))
        ):
            result = filter_metabolite_maps(self.config, "01", "01", {"CrPCr": self.met_path}, self.brainmask_path)

        # np.eye(4) affine -> 1mm isotropic zooms -> nearer to the 7T regime (9).
        self.assertEqual(get_spike_mask_mock.call_args.kwargs["max_cluster_voxels"], 9)
        self.assertEqual(result["CrPCr"], out)
        self.assertTrue(out.exists())
        self.assertTrue(mask_out.exists())

    def test_explicit_max_cluster_voxels_is_passed_through_unchanged(self):
        self.config.spike_max_cluster_voxels = 42
        out = self._signal_out_path()
        mask_out = self._mask_out_path()
        with patch("mrsiprep.mrsi.filtering.mrsi_derivative", side_effect=[out, mask_out]), patch(
            "mrsiprep.mrsi.filtering.get_spike_mask", return_value=np.zeros((6, 6, 6), dtype=bool)
        ) as get_spike_mask_mock, patch(
            "mrsiprep.mrsi.filtering.biharmonic_repair", return_value=(np.ones((6, 6, 6), dtype=np.float32), np.zeros((6, 6, 6), dtype=bool))
        ):
            filter_metabolite_maps(self.config, "01", "01", {"CrPCr": self.met_path}, self.brainmask_path)

        self.assertEqual(get_spike_mask_mock.call_args.kwargs["max_cluster_voxels"], 42)


if __name__ == "__main__":
    unittest.main()

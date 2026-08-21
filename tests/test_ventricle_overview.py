import os
import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.io.naming import coverage_report_dir
from mrsiprep.reports.ventricle_overview import (
    _best_slice_by_voxel_count,
    _detect_ventricle_mask,
    _mni_to_native_affine,
    _warp_prior_to_native,
    _world_bbox_center_and_extent,
    build_ventricle_qc_sections,
)

FSL_HOME = Path("/home/ecelereau/fsl")
HAS_LOCAL_FSL_ATLASES = (FSL_HOME / "data" / "atlases" / "HarvardOxford" / "HarvardOxford-sub-prob-2mm.nii.gz").exists()


def _make_config(tmp_path: Path) -> MRSIPrepConfig:
    return MRSIPrepConfig(
        tmp_path / "bids",
        tmp_path / "derivatives",
        "participant",
        participant_label=["S001"],
        session_label=["V1"],
        metabolites=["CrPCr"],
        ref_met="CrPCr",
    )


def _save_volume(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data.astype("float32"), affine if affine is not None else np.eye(4)), path)
    return path


class WorldBboxCenterAndExtentTests(unittest.TestCase):
    def test_center_and_extent_match_a_known_cube(self):
        mask = np.zeros((10, 10, 10), dtype=bool)
        mask[2:5, 2:5, 2:5] = True  # 3-voxel cube, corners at 2 and 4
        center, extent = _world_bbox_center_and_extent(mask, np.eye(4))
        np.testing.assert_allclose(center, [3.0, 3.0, 3.0])
        np.testing.assert_allclose(extent, [2.0, 2.0, 2.0])


class MniToNativeAffineTests(unittest.TestCase):
    def test_scale_is_per_axis_not_isotropic(self):
        mni_mask = np.zeros((20, 20, 20), dtype=bool)
        mni_mask[0:20, 0:20, 0:20] = True
        native_mask = np.zeros((20, 20, 20), dtype=bool)
        native_mask[0:10, 0:10, 0:5] = True  # z truncated relative to x/y
        placement = _mni_to_native_affine(native_mask, np.eye(4), mni_mask, np.eye(4))
        self.assertIsNotNone(placement)
        _, _, scale = placement
        self.assertAlmostEqual(scale[0], scale[1], places=6)
        self.assertLess(scale[2], scale[0])

    def test_returns_none_for_empty_mask(self):
        empty = np.zeros((5, 5, 5), dtype=bool)
        full = np.ones((5, 5, 5), dtype=bool)
        self.assertIsNone(_mni_to_native_affine(empty, np.eye(4), full, np.eye(4)))


class WarpPriorToNativeTests(unittest.TestCase):
    def test_warped_prior_lands_at_the_expected_native_location(self):
        mni_prob = np.zeros((20, 20, 20), dtype=np.float32)
        mni_prob[9:11, 9:11, 9:11] = 100.0  # a small bright blob at MNI center
        mni_center = np.array([9.5, 9.5, 9.5])
        native_center = np.array([4.5, 4.5, 4.5])
        scale = np.array([1.0, 1.0, 1.0])
        warped = _warp_prior_to_native(mni_prob, np.eye(4), (10, 10, 10), np.eye(4), mni_center, native_center, scale)
        self.assertTrue(warped.any())
        idx = np.argwhere(warped)
        np.testing.assert_allclose(idx.mean(axis=0), [4.5, 4.5, 4.5], atol=1.0)


class DetectVentricleMaskTests(unittest.TestCase):
    def test_detects_a_genuinely_darker_region(self):
        signal = np.full((10, 10, 10), 100.0, dtype=np.float32)
        signal[4:6, 4:6, 4:6] = 1.0  # dark blob where the prior points
        prior = np.zeros((10, 10, 10), dtype=bool)
        prior[4:6, 4:6, 4:6] = True
        brainmask = np.ones((10, 10, 10), dtype=bool)
        detected = _detect_ventricle_mask(signal, prior, brainmask)
        self.assertTrue(detected[4:6, 4:6, 4:6].all())

    def test_empty_reference_shell_returns_empty_mask(self):
        signal = np.ones((3, 3, 3), dtype=np.float32)
        prior = np.ones((3, 3, 3), dtype=bool)  # fills the whole brainmask, no shell possible
        brainmask = np.ones((3, 3, 3), dtype=bool)
        detected = _detect_ventricle_mask(signal, prior, brainmask)
        self.assertFalse(detected.any())


class BestSliceByVoxelCountTests(unittest.TestCase):
    def test_picks_the_slice_with_the_most_detected_voxels(self):
        detected = np.zeros((5, 5, 4), dtype=bool)
        detected[:, :, 1] = True  # slice 1 has the most
        detected[0, 0, 2] = True
        self.assertEqual(_best_slice_by_voxel_count(detected), 1)

    def test_returns_none_below_min_voxels(self):
        detected = np.zeros((5, 5, 4), dtype=bool)
        detected[0, 0, 2] = True  # only 1 voxel anywhere
        self.assertIsNone(_best_slice_by_voxel_count(detected, min_voxels=3))


class BuildVentricleQcSectionsTests(unittest.TestCase):
    def test_returns_empty_without_fsldir(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw = np.random.uniform(0, 5, size=(20, 20, 20)).astype(np.float32)
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", raw)}
            old_fsldir = os.environ.pop("FSLDIR", None)
            try:
                sections = build_ventricle_qc_sections(config, "S001", "V1", raw_maps)
            finally:
                if old_fsldir is not None:
                    os.environ["FSLDIR"] = old_fsldir
            self.assertEqual(sections, [])

    def test_handles_no_metabolites_without_fsldir(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            old_fsldir = os.environ.pop("FSLDIR", None)
            try:
                sections = build_ventricle_qc_sections(config, "S001", "V1", {})
            finally:
                if old_fsldir is not None:
                    os.environ["FSLDIR"] = old_fsldir
            self.assertEqual(sections, [])

    @unittest.skipUnless(HAS_LOCAL_FSL_ATLASES, "requires a local FSL install with atlas data (not just the base package)")
    def test_end_to_end_with_real_fsl_atlas_data(self):
        """Integration test against the real Harvard-Oxford atlas: builds a
        native-space volume with a made-up brain extent and confirms the
        full pipeline (prior placement, warp, detection, best-slice
        selection, rendering) runs and produces a figure, without
        asserting anything about ventricle location on synthetic data."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            rng = np.random.default_rng(0)
            # A native MRSI-like grid (44x44x25, ~5mm voxels) with a
            # spherical brain-shaped signal blob, matching the rough
            # geometry of a real whole-brain MRSI acquisition.
            shape = (44, 44, 25)
            signal = rng.uniform(1.0, 3.0, size=shape).astype(np.float32)
            zz, yy, xx = np.meshgrid(*(np.arange(s) for s in shape), indexing="ij")
            center = np.array(shape) / 2
            radius = np.array([18, 18, 10])
            inside = (((zz - center[0]) / radius[0]) ** 2 + ((yy - center[1]) / radius[1]) ** 2 + ((xx - center[2]) / radius[2]) ** 2) <= 1
            signal[~inside] = 0.0
            affine = np.diag([5.0, 5.0, 5.2, 1.0])
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", signal, affine)}

            old_fsldir = os.environ.get("FSLDIR")
            os.environ["FSLDIR"] = str(FSL_HOME)
            try:
                sections = build_ventricle_qc_sections(config, "S001", "V1", raw_maps)
            finally:
                if old_fsldir is None:
                    os.environ.pop("FSLDIR", None)
                else:
                    os.environ["FSLDIR"] = old_fsldir

            self.assertEqual(len(sections), 1)
            heading, body = sections[0]
            self.assertIn("Ventricle", heading)
            self.assertIn("ventricle-qc.png", body)
            figures_dir = coverage_report_dir(config.derivative_dir, "S001", "V1") / "figures"
            self.assertEqual(len(list(figures_dir.glob("*ventricle-qc.png"))), 1)


if __name__ == "__main__":
    unittest.main()

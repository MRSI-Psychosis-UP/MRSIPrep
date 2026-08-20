import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.reports.ventricle_overview import (
    MAX_MONTAGE_COLUMNS,
    _best_slice_by_voxel_count,
    _fsl_standard_path,
    _load_canonical,
    _mni_brain_mask,
    _lateral_ventricle_prior,
    _render_ventricle_montage,
    _world_bbox_center_and_extent,
    build_ventricle_qc_sections,
)


class FslStandardPathTests(unittest.TestCase):
    def test_returns_none_when_fsldir_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(_fsl_standard_path(Path("data/standard/thing.nii.gz")))

    def test_returns_none_when_file_missing_under_fsldir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"FSLDIR": tmpdir}, clear=True):
                self.assertIsNone(_fsl_standard_path(Path("data/standard/missing.nii.gz")))

    def test_returns_resolved_path_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            relative = Path("data/standard/thing.nii.gz")
            full = Path(tmpdir) / relative
            full.parent.mkdir(parents=True)
            full.touch()
            with patch.dict("os.environ", {"FSLDIR": tmpdir}, clear=True):
                self.assertEqual(_fsl_standard_path(relative), full)


class LoadCanonicalTests(unittest.TestCase):
    def test_loads_3d_volume_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "vol.nii.gz"
            data = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
            nib.save(nib.Nifti1Image(data, np.eye(4)), path)
            loaded, affine = _load_canonical(path)
        self.assertEqual(loaded.shape, (2, 3, 4))
        np.testing.assert_allclose(affine, np.eye(4))

    def test_squeezes_4d_volume_to_first_frame(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "vol4d.nii.gz"
            data = np.stack([np.ones((2, 3, 4)), np.full((2, 3, 4), 9.0)], axis=-1).astype(np.float32)
            nib.save(nib.Nifti1Image(data, np.eye(4)), path)
            loaded, _ = _load_canonical(path)
        self.assertEqual(loaded.shape, (2, 3, 4))
        np.testing.assert_allclose(loaded, np.ones((2, 3, 4)))


class WorldBboxCenterAndExtentTests(unittest.TestCase):
    def test_identity_affine_matches_voxel_bbox(self):
        mask = np.zeros((10, 10, 10), dtype=bool)
        mask[2:5, 3:6, 4:7] = True  # occupies indices 2-4, 3-5, 4-6
        center, extent = _world_bbox_center_and_extent(mask, np.eye(4))
        np.testing.assert_allclose(center, [3.0, 4.0, 5.0])
        np.testing.assert_allclose(extent, [2.0, 2.0, 2.0])

    def test_scaled_affine_scales_the_extent(self):
        mask = np.zeros((10, 10, 10), dtype=bool)
        mask[0:2, 0:2, 0:2] = True
        affine = np.diag([2.0, 2.0, 2.0, 1.0])
        _, extent = _world_bbox_center_and_extent(mask, affine)
        np.testing.assert_allclose(extent, [2.0, 2.0, 2.0])  # 1 voxel of span * scale 2


class BestSliceByVoxelCountTests(unittest.TestCase):
    def test_returns_slice_index_with_most_detected_voxels(self):
        detected = np.zeros((5, 5, 4), dtype=bool)
        detected[:, :, 2] = True  # every voxel in slice z=2
        self.assertEqual(_best_slice_by_voxel_count(detected, min_voxels=3), 2)

    def test_returns_none_when_below_minimum(self):
        detected = np.zeros((5, 5, 4), dtype=bool)
        detected[0, 0, 1] = True  # only 1 voxel anywhere
        self.assertIsNone(_best_slice_by_voxel_count(detected, min_voxels=3))


class LateralVentriclePriorTests(unittest.TestCase):
    def test_none_when_atlas_unavailable(self):
        with patch("mrsiprep.reports.ventricle_overview._fsl_standard_path", return_value=None):
            self.assertIsNone(_lateral_ventricle_prior())

    def test_combines_left_and_right_ventricle_channels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            atlas_path = Path(tmpdir) / "atlas.nii.gz"
            data = np.zeros((4, 4, 4, 21), dtype=np.float32)
            data[1, 1, 1, 2] = 60.0  # left lateral ventricle channel
            data[1, 1, 1, 13] = 70.0  # right lateral ventricle channel -- combined should clip to 100
            nib.save(nib.Nifti1Image(data, np.eye(4)), atlas_path)
            with patch("mrsiprep.reports.ventricle_overview._fsl_standard_path", return_value=atlas_path):
                combined, affine = _lateral_ventricle_prior()
        self.assertEqual(combined[1, 1, 1], 100.0)  # 60 + 70 clipped to 100
        self.assertEqual(combined[0, 0, 0], 0.0)


class MniBrainMaskTests(unittest.TestCase):
    def test_none_when_mask_unavailable(self):
        with patch("mrsiprep.reports.ventricle_overview._fsl_standard_path", return_value=None):
            self.assertIsNone(_mni_brain_mask())

    def test_thresholds_to_boolean(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mask_path = Path(tmpdir) / "mask.nii.gz"
            data = np.array([[[0.0, 1.0], [0.5, 0.0]]], dtype=np.float32)
            nib.save(nib.Nifti1Image(data, np.eye(4)), mask_path)
            with patch("mrsiprep.reports.ventricle_overview._fsl_standard_path", return_value=mask_path):
                mask, _ = _mni_brain_mask()
        self.assertEqual(mask.dtype, np.bool_)
        self.assertTrue(mask[0, 0, 1])
        self.assertFalse(mask[0, 0, 0])


class RenderVentricleMontageTests(unittest.TestCase):
    def test_wraps_rows_beyond_max_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "montage.png"
            n_metabolites = MAX_MONTAGE_COLUMNS + 2  # forces a second row
            panels = []
            for i in range(n_metabolites):
                signal = np.ones((4, 4, 3), dtype=np.float32)
                prior_roi = np.zeros((4, 4, 3), dtype=bool)
                detected = np.zeros((4, 4, 3), dtype=bool)
                panels.append((f"MET{i}", signal, prior_roi, detected, 1))
            result = _render_ventricle_montage(panels, out_path)
            self.assertEqual(result, out_path)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)


class BuildVentricleQcSectionsTests(unittest.TestCase):
    def test_returns_empty_when_prior_unavailable(self):
        config = SimpleNamespace(derivative_dir=Path("/tmp/deriv"))
        with patch("mrsiprep.reports.ventricle_overview._lateral_ventricle_prior", return_value=None), patch(
            "mrsiprep.reports.ventricle_overview._mni_brain_mask", return_value=(np.zeros((2, 2, 2), dtype=bool), np.eye(4))
        ):
            self.assertEqual(build_ventricle_qc_sections(config, "01", "01", {}), [])

    def test_returns_empty_when_mni_brain_mask_unavailable(self):
        config = SimpleNamespace(derivative_dir=Path("/tmp/deriv"))
        with patch(
            "mrsiprep.reports.ventricle_overview._lateral_ventricle_prior", return_value=(np.zeros((2, 2, 2)), np.eye(4))
        ), patch("mrsiprep.reports.ventricle_overview._mni_brain_mask", return_value=None):
            self.assertEqual(build_ventricle_qc_sections(config, "01", "01", {}), [])

    def test_skips_metabolites_with_no_placement_or_detection_and_still_renders_others(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SimpleNamespace(derivative_dir=Path(tmpdir) / "derivatives" / "mrsiprep")
            # sorted(raw_maps) iterates as ["Good", "NoDetection", "NoPlacement"];
            # the three side_effect lists below are keyed to that exact order.
            raw_maps = {"NoPlacement": Path("a.nii.gz"), "NoDetection": Path("b.nii.gz"), "Good": Path("c.nii.gz")}
            fake_signal = np.ones((4, 4, 3), dtype=np.float32)
            valid_placement = ("c", "c", np.array([1.0, 1.0, 1.0]))

            with patch("mrsiprep.reports.ventricle_overview._lateral_ventricle_prior", return_value=(np.zeros((4, 4, 3)), np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._mni_brain_mask", return_value=(np.ones((4, 4, 3), dtype=bool), np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._load_canonical", side_effect=lambda p: (fake_signal, np.eye(4))), \
                patch(
                    "mrsiprep.reports.ventricle_overview._mni_to_native_affine",
                    # Good -> valid; NoDetection -> valid (fails later at best-slice); NoPlacement -> None.
                    side_effect=[valid_placement, valid_placement, None],
                ), \
                patch("mrsiprep.reports.ventricle_overview._warp_prior_to_native", return_value=np.ones((4, 4, 3), dtype=bool)), \
                patch("mrsiprep.reports.ventricle_overview._detect_ventricle_mask", return_value=np.ones((4, 4, 3), dtype=bool)), \
                patch(
                    "mrsiprep.reports.ventricle_overview._best_slice_by_voxel_count",
                    # Only called for the two metabolites with a valid placement: Good -> 1, NoDetection -> None.
                    side_effect=[1, None],
                ), \
                patch("mrsiprep.reports.ventricle_overview._render_ventricle_montage", return_value=Path(tmpdir) / "out.png") as render:
                sections = build_ventricle_qc_sections(config, "01", "01", raw_maps)

        rendered_panels = render.call_args[0][0]
        self.assertEqual([p[0] for p in rendered_panels], ["Good"])
        self.assertEqual(len(sections), 1)
        title, body = sections[0]
        self.assertIn("Ventricle visibility", title)
        self.assertIn("<img", body)


if __name__ == "__main__":
    unittest.main()

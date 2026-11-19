import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.qc.ventricles import (
    DICE_GOOD,
    MetaboliteVentricles,
    VentricleDice,
    VentricleQC,
    _fsl_standard_path,
    _world_bbox_center_and_extent,
    detect_ventricle_mask,
    detect_ventricles,
    dice,
    lateral_ventricle_prior,
    load_canonical,
    mni_brain_mask,
    mni_to_native_placement,
    run_ventricle_qc,
    score_detections,
    ventricle_reference_mask,
    warp_prior_to_native,
    write_ventricle_qc_tsv,
)

_MOD = "mrsiprep.qc.ventricles"


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
            loaded, affine = load_canonical(path)
        self.assertEqual(loaded.shape, (2, 3, 4))
        np.testing.assert_allclose(affine, np.eye(4))

    def test_squeezes_4d_volume_to_first_frame(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "vol4d.nii.gz"
            data = np.stack([np.ones((2, 3, 4)), np.full((2, 3, 4), 9.0)], axis=-1).astype(np.float32)
            nib.save(nib.Nifti1Image(data, np.eye(4)), path)
            loaded, _ = load_canonical(path)
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


class LateralVentriclePriorTests(unittest.TestCase):
    def test_none_when_atlas_unavailable(self):
        with patch(f"{_MOD}._fsl_standard_path", return_value=None):
            self.assertIsNone(lateral_ventricle_prior())

    def test_combines_left_and_right_ventricle_channels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            atlas_path = Path(tmpdir) / "atlas.nii.gz"
            data = np.zeros((4, 4, 4, 21), dtype=np.float32)
            data[1, 1, 1, 2] = 60.0  # left lateral ventricle channel
            data[1, 1, 1, 13] = 70.0  # right lateral ventricle channel -- combined should clip to 100
            nib.save(nib.Nifti1Image(data, np.eye(4)), atlas_path)
            with patch(f"{_MOD}._fsl_standard_path", return_value=atlas_path):
                combined, affine = lateral_ventricle_prior()
        self.assertEqual(combined[1, 1, 1], 100.0)  # 60 + 70 clipped to 100
        self.assertEqual(combined[0, 0, 0], 0.0)


class MniBrainMaskTests(unittest.TestCase):
    """The mask comes from the run's reference template, with FSL's copy
    kept only as a fallback -- FSL ships the MNI152NLin6Asym lineage, so it
    describes a different space than the data being checked."""

    def _mask_img(self):
        data = np.array([[[0.0, 1.0], [0.5, 0.0]]], dtype=np.float32)
        return nib.Nifti1Image(data, np.eye(4))

    def test_prefers_the_reference_template(self):
        with patch("mrsiprep.config.templates.template_brain_mask", return_value=self._mask_img()), patch(
            f"{_MOD}._fsl_standard_path"
        ) as fsl:
            mask, _ = mni_brain_mask()
        fsl.assert_not_called()
        self.assertEqual(mask.dtype, np.bool_)
        self.assertTrue(mask[0, 0, 1])
        self.assertFalse(mask[0, 0, 0])

    def test_falls_back_to_fsl_when_the_template_is_unavailable(self):
        from mrsiprep.config.templates import TemplateError

        with tempfile.TemporaryDirectory() as tmpdir:
            mask_path = Path(tmpdir) / "mask.nii.gz"
            nib.save(self._mask_img(), mask_path)
            with patch("mrsiprep.config.templates.template_brain_mask", side_effect=TemplateError("no cache")), patch(
                f"{_MOD}._fsl_standard_path", return_value=mask_path
            ):
                mask, _ = mni_brain_mask()
        self.assertEqual(mask.dtype, np.bool_)
        self.assertTrue(mask[0, 0, 1])

    def test_none_when_neither_source_is_available(self):
        from mrsiprep.config.templates import TemplateError

        with patch("mrsiprep.config.templates.template_brain_mask", side_effect=TemplateError("no cache")), patch(
            f"{_MOD}._fsl_standard_path", return_value=None
        ):
            self.assertIsNone(mni_brain_mask())


class MniToNativePlacementTests(unittest.TestCase):
    def test_scale_is_per_axis_not_isotropic(self):
        mni_mask = np.ones((20, 20, 20), dtype=bool)
        native_mask = np.zeros((20, 20, 20), dtype=bool)
        native_mask[0:10, 0:10, 0:5] = True  # z truncated relative to x/y
        placement = mni_to_native_placement(native_mask, np.eye(4), mni_mask, np.eye(4))
        self.assertIsNotNone(placement)
        _, _, scale = placement
        self.assertAlmostEqual(scale[0], scale[1], places=6)
        self.assertLess(scale[2], scale[0])

    def test_returns_none_for_empty_mask(self):
        empty = np.zeros((5, 5, 5), dtype=bool)
        full = np.ones((5, 5, 5), dtype=bool)
        self.assertIsNone(mni_to_native_placement(empty, np.eye(4), full, np.eye(4)))


class WarpPriorToNativeTests(unittest.TestCase):
    def test_warped_prior_lands_at_the_expected_native_location(self):
        mni_prob = np.zeros((20, 20, 20), dtype=np.float32)
        mni_prob[9:11, 9:11, 9:11] = 100.0  # a small bright blob at MNI center
        warped = warp_prior_to_native(
            mni_prob, np.eye(4), (10, 10, 10), np.eye(4), np.array([9.5, 9.5, 9.5]), np.array([4.5, 4.5, 4.5]), np.ones(3)
        )
        self.assertTrue(warped.any())
        np.testing.assert_allclose(np.argwhere(warped).mean(axis=0), [4.5, 4.5, 4.5], atol=1.0)


class DetectVentricleMaskTests(unittest.TestCase):
    def test_detects_a_genuinely_darker_region(self):
        signal = np.full((10, 10, 10), 100.0, dtype=np.float32)
        signal[4:6, 4:6, 4:6] = 1.0  # dark blob where the prior points
        prior = np.zeros((10, 10, 10), dtype=bool)
        prior[4:6, 4:6, 4:6] = True
        detected = detect_ventricle_mask(signal, prior, np.ones((10, 10, 10), dtype=bool))
        self.assertTrue(detected[4:6, 4:6, 4:6].all())

    def test_empty_reference_shell_returns_empty_mask(self):
        signal = np.ones((3, 3, 3), dtype=np.float32)
        prior = np.ones((3, 3, 3), dtype=bool)  # fills the whole brainmask, no shell possible
        detected = detect_ventricle_mask(signal, prior, np.ones((3, 3, 3), dtype=bool))
        self.assertFalse(detected.any())


class DiceTests(unittest.TestCase):
    def test_identical_masks_score_one(self):
        a = np.zeros((4, 4, 4), dtype=bool)
        a[1:3, 1:3, 1:3] = True
        self.assertEqual(dice(a, a), 1.0)

    def test_disjoint_masks_score_zero(self):
        a = np.zeros((4, 4, 4), dtype=bool)
        b = np.zeros((4, 4, 4), dtype=bool)
        a[0, 0, 0] = True
        b[3, 3, 3] = True
        self.assertEqual(dice(a, b), 0.0)

    def test_two_empty_masks_score_zero_not_nan(self):
        empty = np.zeros((2, 2, 2), dtype=bool)
        self.assertEqual(dice(empty, empty), 0.0)


def _detection(met, detected, shape=(4, 4, 3)):
    return MetaboliteVentricles(met, np.ones(shape, dtype=np.float32), np.zeros(shape, dtype=bool), detected, np.ones(shape, dtype=bool))


class DetectVentriclesTests(unittest.TestCase):
    def test_none_when_the_atlas_is_unavailable(self):
        with patch(f"{_MOD}.lateral_ventricle_prior", return_value=None), patch(
            f"{_MOD}.mni_brain_mask", return_value=(np.ones((2, 2, 2), dtype=bool), np.eye(4))
        ):
            self.assertIsNone(detect_ventricles({"CrPCr": Path("c.nii.gz")}))

    def test_skips_maps_without_a_placement_but_keeps_undetected_ones(self):
        """A failed placement drops a metabolite (there is no sensible prior);
        a valid placement with nothing detected is kept, since an empty
        detection is itself the result."""
        good = np.zeros((4, 4, 3), dtype=bool)
        good[:, :, 1] = True
        empty = np.zeros((4, 4, 3), dtype=bool)
        valid = ("c", "c", np.ones(3))
        # sorted order: Good, NoDetection, NoPlacement
        raw_maps = {"NoPlacement": Path("a.nii.gz"), "NoDetection": Path("b.nii.gz"), "Good": Path("c.nii.gz")}
        with patch(f"{_MOD}.lateral_ventricle_prior", return_value=(np.zeros((4, 4, 3)), np.eye(4))), patch(
            f"{_MOD}.mni_brain_mask", return_value=(np.ones((4, 4, 3), dtype=bool), np.eye(4))
        ), patch(f"{_MOD}.load_canonical", return_value=(np.ones((4, 4, 3), dtype=np.float32), np.eye(4))), patch(
            f"{_MOD}.mni_to_native_placement", side_effect=[valid, valid, None]
        ), patch(f"{_MOD}.warp_prior_to_native", return_value=np.ones((4, 4, 3), dtype=bool)), patch(
            f"{_MOD}.detect_ventricle_mask", side_effect=[good, empty]
        ):
            detections = detect_ventricles(raw_maps)
        self.assertEqual([d.metabolite for d in detections], ["Good", "NoDetection"])
        self.assertTrue(detections[0].detected.any())
        self.assertFalse(detections[1].detected.any())


class ScoreDetectionsTests(unittest.TestCase):
    def test_scores_each_detection_against_the_reference(self):
        reference = np.zeros((4, 4, 3), dtype=bool)
        reference[:2, :, 1] = True
        miss = np.zeros((4, 4, 3), dtype=bool)
        miss[3, 3, 0] = True
        scores = score_detections([_detection("A", reference.copy()), _detection("B", miss)], reference)
        self.assertEqual([(s.metabolite, s.dice) for s in scores], [("A", 1.0), ("B", 0.0)])
        self.assertEqual(scores[0].n_reference, int(reference.sum()))

    def test_restricts_the_reference_to_each_maps_coverage(self):
        reference = np.ones((4, 4, 3), dtype=bool)
        det = _detection("A", reference.copy())
        det.brainmask[:] = False
        det.brainmask[0, 0, 0] = True
        det.detected = det.brainmask.copy()
        self.assertEqual(score_detections([det], reference)[0].dice, 1.0)

    def test_skips_maps_on_another_grid(self):
        self.assertEqual(score_detections([_detection("A", np.zeros((2, 2, 2), dtype=bool), (2, 2, 2))], np.ones((4, 4, 3), dtype=bool)), [])


class VentricleQcResultTests(unittest.TestCase):
    def test_median_and_pass_flag(self):
        result = VentricleQC(dice=[VentricleDice("A", 0.30, 1, 1), VentricleDice("B", 0.10, 1, 1), VentricleDice("C", DICE_GOOD, 1, 1)])
        self.assertAlmostEqual(result.median_dice, DICE_GOOD)
        self.assertTrue(result.passed)
        self.assertFalse(VentricleQC(dice=[VentricleDice("A", 0.05, 1, 1)]).passed)

    def test_no_reference_means_no_verdict(self):
        result = VentricleQC(detections=[_detection("A", np.zeros((4, 4, 3), dtype=bool))])
        self.assertIsNone(result.median_dice)
        self.assertIsNone(result.passed)


class RunVentricleQcTests(unittest.TestCase):
    def test_none_without_the_atlas(self):
        with patch(f"{_MOD}.detect_ventricles", return_value=None):
            self.assertIsNone(run_ventricle_qc({"CrPCr": Path("c.nii.gz")}))

    def test_scores_only_when_a_reference_exists(self):
        detected = np.zeros((4, 4, 3), dtype=bool)
        detected[0, 0, 0] = True
        with tempfile.TemporaryDirectory() as tmpdir:
            vent = Path(tmpdir) / "vent.nii.gz"
            nib.save(nib.Nifti1Image(detected.astype(np.uint8), np.eye(4)), vent)
            with patch(f"{_MOD}.detect_ventricles", return_value=[_detection("A", detected)]):
                without = run_ventricle_qc({"A": Path("a.nii.gz")})
                missing = run_ventricle_qc({"A": Path("a.nii.gz")}, reference_ventricles=Path(tmpdir) / "absent.nii.gz")
                with_ref = run_ventricle_qc({"A": Path("a.nii.gz")}, reference_ventricles=vent)
        self.assertEqual(without.dice, [])
        self.assertEqual(missing.dice, [])
        self.assertEqual(with_ref.median_dice, 1.0)


class WriteVentricleQcTsvTests(unittest.TestCase):
    def test_one_row_per_metabolite_plus_median(self):
        result = VentricleQC(dice=[VentricleDice("CrPCr", 1.0, 8, 8), VentricleDice("Glu", 0.0, 1, 8)])
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = write_ventricle_qc_tsv(result, Path(tmpdir) / "q.tsv").read_text().splitlines()
        self.assertEqual(rows[0].split("\t"), ["metabolite", "dice", "n_detected", "n_reference"])
        self.assertEqual(rows[1].split("\t"), ["CrPCr", "1.0", "8", "8"])
        self.assertEqual(rows[3].split("\t")[:2], ["median", "0.5"])


class VentricleReferenceMaskTests(unittest.TestCase):
    def test_none_without_a_transform(self):
        config = SimpleNamespace(derivative_dir=Path("/tmp/deriv"), work_dir=Path("/tmp/work"))
        self.assertIsNone(ventricle_reference_mask(config, "01", "01", Path("t1.nii.gz"), Path("ref.nii.gz"), []))


if __name__ == "__main__":
    unittest.main()

import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import nibabel as nib
import numpy as np

from mrsiprep.mrsi.t1_correction import (
    T1CorrectionError,
    apply_t1_correction,
    apply_t1_correction_voxelwise,
    ernst_saturation_factor,
    ernst_saturation_factor_map,
    resolve_acquisition_params,
    resolve_metabolite_t1,
)
from mrsiprep.config.t1_values import load_t1_literature_values


def _config(root: Path, **overrides) -> SimpleNamespace:
    defaults = dict(derivative_dir=root / "derivatives", work_dir=root / "work", overwrite=False, overwrite_t1corr=False)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class ErnstSaturationFactorTests(unittest.TestCase):
    def test_matches_hand_computed_value(self):
        tr_s, flip_deg, t1_s = 2.0, 90.0, 1.38
        factor = ernst_saturation_factor(tr_s, flip_deg, t1_s)
        e1 = math.exp(-tr_s / t1_s)
        expected = (1 - math.cos(math.radians(flip_deg)) * e1) / (math.sin(math.radians(flip_deg)) * (1 - e1))
        self.assertAlmostEqual(factor, expected, places=10)

    def test_long_tr_approaches_full_recovery(self):
        factor = ernst_saturation_factor(tr_s=100.0, flip_deg=90.0, t1_s=1.38)
        self.assertAlmostEqual(factor, 1.0, places=3)


class ResolveMetaboliteT1Tests(unittest.TestCase):
    def test_loads_json_config(self):
        values = load_t1_literature_values()
        self.assertIn("CrPCr", values)
        self.assertIn(3.0, values["CrPCr"])
        self.assertAlmostEqual(values["CrPCr"][3.0]["t1_s"], 1.38)

    def test_verified_entry_returned(self):
        entry = resolve_metabolite_t1("CrPCr", 3.0)
        self.assertEqual(entry["status"], "verified")
        self.assertAlmostEqual(entry["t1_s"], 1.38)

    def test_proxy_or_derived_entry_returned_when_t1_is_curated(self):
        entry = resolve_metabolite_t1("NAANAAG", 3.0)
        self.assertEqual(entry["status"], "proxy")
        self.assertAlmostEqual(entry["t1_s"], 1.38)

    def test_rejects_unknown_metabolite_without_alias_fallback(self):
        with self.assertRaisesRegex(T1CorrectionError, "No literature T1 database entry"):
            resolve_metabolite_t1("tNAA", 3.0)

    def test_rejects_todo_status_entry(self):
        with self.assertRaisesRegex(T1CorrectionError, "not yet curated"):
            resolve_metabolite_t1("Gln", 3.0)

    def test_rejects_unsupported_field_strength(self):
        with self.assertRaisesRegex(T1CorrectionError, "No literature T1 value"):
            resolve_metabolite_t1("CrPCr", 1.5)


class ResolveAcquisitionParamsTests(unittest.TestCase):
    def test_valid_metadata(self):
        params = resolve_acquisition_params({"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0})
        self.assertEqual(params.tr_s, 2.0)
        self.assertEqual(params.flip_deg, 90.0)
        self.assertEqual(params.field_strength_t, 3.0)

    def test_rejects_missing_metadata(self):
        with self.assertRaisesRegex(T1CorrectionError, "requires a dataset-level mrsinmrs.json"):
            resolve_acquisition_params(None)

    def test_rejects_missing_tr_field(self):
        with self.assertRaisesRegex(T1CorrectionError, "missing a recognized 'TR' field"):
            resolve_acquisition_params({"FlipAngle": 90.0, "MagneticFieldStrength": 3.0})

    def test_rejects_ambiguous_tr_field(self):
        with self.assertRaisesRegex(T1CorrectionError, "conflicting values"):
            resolve_acquisition_params({"RepetitionTime": 2.0, "TR": 2.5, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0})

    def test_rejects_implausible_tr_units(self):
        with self.assertRaisesRegex(T1CorrectionError, "plausible TR range"):
            resolve_acquisition_params({"RepetitionTime": 2000.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0})


class ApplyT1CorrectionTests(unittest.TestCase):
    def test_writes_signalt1corr_output_with_correct_scaling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = nib.Nifti1Image(np.full((2, 2, 2), 4.0, dtype=np.float32), np.eye(4))
            metabolite = root / "CrPCr.nii.gz"
            nib.save(image, metabolite)
            config = _config(root)
            params = resolve_acquisition_params({"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0})

            corrected, rows, summary = apply_t1_correction(config, "S001", "V1", {"CrPCr": metabolite}, params, "unknown")

            out_path = corrected["CrPCr"]
            self.assertIn("orig-t1corr", str(out_path))
            self.assertIn("desc-signalt1corr", out_path.name)
            factor = ernst_saturation_factor(2.0, 90.0, 1.38)
            result = nib.load(str(out_path)).get_fdata()
            np.testing.assert_allclose(result, 4.0 * factor, rtol=1e-5)
            self.assertEqual(rows[0]["metabolite"], "CrPCr")
            self.assertIn("Water-referencing status unknown", rows[0]["warnings"])
            self.assertTrue(summary.exists())
            self.assertIn("desc-t1corr", summary.name)

    def test_skips_recompute_when_cached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4))
            metabolite = root / "CrPCr.nii.gz"
            nib.save(image, metabolite)
            config = _config(root)
            params = resolve_acquisition_params({"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0})

            corrected1, _, _ = apply_t1_correction(config, "S001", "V1", {"CrPCr": metabolite}, params, "unknown")
            mtime1 = corrected1["CrPCr"].stat().st_mtime_ns
            corrected2, _, _ = apply_t1_correction(config, "S001", "V1", {"CrPCr": metabolite}, params, "unknown")
            mtime2 = corrected2["CrPCr"].stat().st_mtime_ns
            self.assertEqual(mtime1, mtime2)

    def test_raises_for_uncurated_metabolite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4))
            metabolite = root / "Gln.nii.gz"
            nib.save(image, metabolite)
            config = _config(root)
            params = resolve_acquisition_params({"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0})

            with self.assertRaises(T1CorrectionError):
                apply_t1_correction(config, "S001", "V1", {"Gln": metabolite}, params, "unknown")


class ErnstSaturationFactorMapTests(unittest.TestCase):
    def test_matches_scalar_version_at_each_voxel(self):
        tr_s, t1_s = 2.0, 1.38
        flip_map = np.array([[[60.0, 90.0], [75.0, 90.0]]], dtype=np.float32)
        factor_map = ernst_saturation_factor_map(tr_s, flip_map, t1_s)
        for idx in np.ndindex(flip_map.shape):
            expected = ernst_saturation_factor(tr_s, float(flip_map[idx]), t1_s)
            self.assertAlmostEqual(factor_map[idx], expected, places=5)

    def test_non_physical_voxel_is_nan_not_an_exception(self):
        # flip_deg=0 -> sin(alpha)=0 -> denominator <= 0 everywhere TR/T1 finite.
        flip_map = np.array([[[0.0, 90.0]]], dtype=np.float32)
        factor_map = ernst_saturation_factor_map(2.0, flip_map, 1.38)
        self.assertTrue(np.isnan(factor_map[0, 0, 0]))
        self.assertFalse(np.isnan(factor_map[0, 0, 1]))


class ApplyT1CorrectionVoxelwiseTests(unittest.TestCase):
    def test_writes_signalt1corrvoxelwise_output_with_per_voxel_scaling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = nib.Nifti1Image(np.full((2, 2, 2), 4.0, dtype=np.float32), np.eye(4))
            metabolite = root / "CrPCr.nii.gz"
            nib.save(image, metabolite)
            # Two distinct flip angles so the correction is genuinely per-voxel.
            flip_data = np.full((2, 2, 2), 90.0, dtype=np.float32)
            flip_data[0, 0, 0] = 60.0
            flip_map_path = root / "b1map.nii.gz"
            nib.save(nib.Nifti1Image(flip_data, np.eye(4)), flip_map_path)
            config = _config(root)
            params = resolve_acquisition_params({"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0})

            corrected, rows, summary = apply_t1_correction_voxelwise(
                config, "S001", "V1", {"CrPCr": metabolite}, flip_map_path, params, "unknown"
            )

            out_path = corrected["CrPCr"]
            self.assertIn("orig-t1corr", str(out_path))
            self.assertIn("desc-signalt1corrvoxelwise", out_path.name)
            result = nib.load(str(out_path)).get_fdata()
            factor_90 = ernst_saturation_factor(2.0, 90.0, 1.38)
            factor_60 = ernst_saturation_factor(2.0, 60.0, 1.38)
            np.testing.assert_allclose(result[0, 0, 0], 4.0 * factor_60, rtol=1e-4)
            np.testing.assert_allclose(result[1, 1, 1], 4.0 * factor_90, rtol=1e-4)
            self.assertEqual(rows[0]["metabolite"], "CrPCr")
            self.assertEqual(rows[0]["flip_angle_map"], str(flip_map_path))
            self.assertAlmostEqual(rows[0]["non_physical_voxel_fraction"], 0.0)
            self.assertIn("Water-referencing status unknown", rows[0]["warnings"])
            self.assertTrue(summary.exists())
            self.assertIn("desc-t1corrvoxelwise", summary.name)

    def test_non_physical_voxels_are_left_uncorrected_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = nib.Nifti1Image(np.full((2, 2, 2), 4.0, dtype=np.float32), np.eye(4))
            metabolite = root / "CrPCr.nii.gz"
            nib.save(image, metabolite)
            flip_data = np.full((2, 2, 2), 90.0, dtype=np.float32)
            flip_data[0, 0, 0] = 0.0  # non-physical: sin(0)=0 -> NaN factor at this voxel
            flip_map_path = root / "b1map.nii.gz"
            nib.save(nib.Nifti1Image(flip_data, np.eye(4)), flip_map_path)
            config = _config(root)
            params = resolve_acquisition_params({"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0})

            corrected, rows, _ = apply_t1_correction_voxelwise(
                config, "S001", "V1", {"CrPCr": metabolite}, flip_map_path, params, "unknown"
            )

            result = nib.load(str(corrected["CrPCr"])).get_fdata()
            self.assertAlmostEqual(result[0, 0, 0], 4.0)  # left uncorrected
            factor_90 = ernst_saturation_factor(2.0, 90.0, 1.38)
            np.testing.assert_allclose(result[1, 1, 1], 4.0 * factor_90, rtol=1e-4)
            self.assertAlmostEqual(rows[0]["non_physical_voxel_fraction"], 1 / 8)

    def test_raises_on_grid_mismatch_with_flip_angle_map(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4))
            metabolite = root / "CrPCr.nii.gz"
            nib.save(image, metabolite)
            flip_map_path = root / "b1map.nii.gz"
            nib.save(nib.Nifti1Image(np.ones((3, 3, 3), dtype=np.float32), np.eye(4)), flip_map_path)
            config = _config(root)
            params = resolve_acquisition_params({"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0})

            with self.assertRaisesRegex(T1CorrectionError, "same grid"):
                apply_t1_correction_voxelwise(config, "S001", "V1", {"CrPCr": metabolite}, flip_map_path, params, "unknown")

    def test_skips_recompute_when_cached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4))
            metabolite = root / "CrPCr.nii.gz"
            nib.save(image, metabolite)
            flip_map_path = root / "b1map.nii.gz"
            nib.save(nib.Nifti1Image(np.full((2, 2, 2), 90.0, dtype=np.float32), np.eye(4)), flip_map_path)
            config = _config(root)
            params = resolve_acquisition_params({"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0})

            corrected1, _, _ = apply_t1_correction_voxelwise(config, "S001", "V1", {"CrPCr": metabolite}, flip_map_path, params, "unknown")
            mtime1 = corrected1["CrPCr"].stat().st_mtime_ns
            corrected2, _, _ = apply_t1_correction_voxelwise(config, "S001", "V1", {"CrPCr": metabolite}, flip_map_path, params, "unknown")
            mtime2 = corrected2["CrPCr"].stat().st_mtime_ns
            self.assertEqual(mtime1, mtime2)


if __name__ == "__main__":
    unittest.main()

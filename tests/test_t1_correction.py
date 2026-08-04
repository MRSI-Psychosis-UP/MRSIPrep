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
    ernst_saturation_factor,
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


if __name__ == "__main__":
    unittest.main()

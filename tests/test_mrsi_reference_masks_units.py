import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import nibabel as nib
import numpy as np

from mrsiprep.mrsi.masks import ensure_brainmask
from mrsiprep.mrsi.reference import generate_reference


def _config(root: Path, **overrides):
    base = dict(derivative_dir=root / "derivatives", overwrite=False, ref_met="CrPCr")
    base.update(overrides)
    return SimpleNamespace(**base)


def _vol(values):
    """Build a (2, 2, 2) volume from 8 values.

    Shapes with a singleton dimension are unusable here: load_3d_data()
    squeezes before its ndim check, so e.g. (1, 1, 2) would collapse to 1D
    and be rejected as "not 3D".
    """
    return np.asarray(values, dtype=np.float32).reshape(2, 2, 2)


def _save(path: Path, values, affine=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = values if isinstance(values, np.ndarray) and values.ndim == 3 else _vol(values)
    nib.save(nib.Nifti1Image(np.asarray(data, dtype=np.float32), np.eye(4) if affine is None else affine), path)
    return path


def _read(path: Path):
    return np.asanyarray(nib.load(str(path)).dataobj)


class EnsureBrainmaskTests(unittest.TestCase):
    def test_existing_mask_is_returned_untouched_without_writing_anything(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            existing = _save(root / "existing.nii.gz", [1] * 8)
            config = _config(root)

            result = ensure_brainmask(config, "S001", "V1", existing, None, {})

            self.assertEqual(result, existing)
            self.assertFalse(config.derivative_dir.exists())

    def test_existing_path_that_does_not_exist_is_ignored_and_mask_is_built(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            water = _save(root / "water.nii.gz", [1] * 8)

            result = ensure_brainmask(_config(root), "S001", "V1", root / "missing.nii.gz", water, {})

            self.assertTrue(result.exists())
            self.assertNotEqual(result, root / "missing.nii.gz")

    def test_water_map_defines_the_mask_as_strictly_positive_voxels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            values = [0.0, 1.0, 2.0, 0.0, -1.0, 0.5, 0.0, 3.0]
            water = _save(root / "water.nii.gz", values)

            result = ensure_brainmask(_config(root), "S001", "V1", None, water, {})

            np.testing.assert_array_equal(_read(result).astype(bool), _vol(values) > 0)

    def test_water_map_takes_precedence_over_metabolite_maps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            water = _save(root / "water.nii.gz", [1, 0, 0, 0, 0, 0, 0, 0])
            met = _save(root / "met.nii.gz", [0, 1, 1, 1, 1, 1, 1, 1])

            result = ensure_brainmask(_config(root), "S001", "V1", None, water, {"CrPCr": met})

            np.testing.assert_array_equal(_read(result).astype(bool), _vol([1, 0, 0, 0, 0, 0, 0, 0]).astype(bool))

    def test_metabolite_maps_are_unioned_when_no_water_map(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            a = _save(root / "a.nii.gz", [1, 0, 0, 0, 0, 0, 0, 0])
            b = _save(root / "b.nii.gz", [0, 2, 0, 0, 0, 0, 0, 0])

            result = ensure_brainmask(_config(root), "S001", "V1", None, None, {"A": a, "B": b})

            np.testing.assert_array_equal(_read(result).astype(bool), _vol([1, 1, 0, 0, 0, 0, 0, 0]).astype(bool))

    def test_non_finite_metabolite_voxels_are_excluded_from_the_union(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            met = _save(root / "met.nii.gz", [np.nan, np.inf, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])

            result = ensure_brainmask(_config(root), "S001", "V1", None, None, {"A": met})

            np.testing.assert_array_equal(_read(result).astype(bool), _vol([0, 0, 1, 0, 0, 0, 0, 0]).astype(bool))

    def test_water_map_that_does_not_exist_falls_through_to_metabolites(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            met = _save(root / "met.nii.gz", [1, 0, 0, 0, 0, 0, 0, 0])

            result = ensure_brainmask(_config(root), "S001", "V1", None, root / "no-water.nii.gz", {"A": met})

            np.testing.assert_array_equal(_read(result).astype(bool), _vol([1, 0, 0, 0, 0, 0, 0, 0]).astype(bool))

    def test_mask_is_written_as_uint8(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            water = _save(root / "water.nii.gz", [1] * 8)

            result = ensure_brainmask(_config(root), "S001", "V1", None, water, {})

            self.assertEqual(nib.load(str(result)).get_data_dtype(), np.uint8)

    def test_no_water_and_no_metabolites_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(ValueError, "without water or metabolite maps"):
                ensure_brainmask(_config(root), "S001", "V1", None, None, {})

    def test_cached_output_is_reused_unless_overwrite_is_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            water = _save(root / "water.nii.gz", [1] * 8)
            config = _config(root)

            first = ensure_brainmask(config, "S001", "V1", None, water, {})
            # Rewrite the cached file with a recognizable sentinel; a cache hit
            # must return it untouched rather than regenerating from the water map.
            _save(first, [7] * 8)
            second = ensure_brainmask(config, "S001", "V1", None, water, {})

            self.assertEqual(first, second)
            self.assertEqual(int(_read(second).max()), 7)

    def test_overwrite_regenerates_the_cached_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            water = _save(root / "water.nii.gz", [1] * 8)

            first = ensure_brainmask(_config(root), "S001", "V1", None, water, {})
            _save(first, [7] * 8)
            second = ensure_brainmask(_config(root, overwrite=True), "S001", "V1", None, water, {})

            self.assertEqual(first, second)
            self.assertEqual(int(_read(second).max()), 1)

    def test_sessionless_subject_still_produces_a_mask(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            water = _save(root / "water.nii.gz", [1] * 8)

            result = ensure_brainmask(_config(root), "S001", None, None, water, {})

            self.assertTrue(result.exists())


class GenerateReferenceTests(unittest.TestCase):
    def test_preferred_metabolite_from_config_is_used_directly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cr = _save(root / "cr.nii.gz", [1, 2, 3, 4, 5, 6, 7, 8])
            other = _save(root / "other.nii.gz", [50] * 8)

            result = generate_reference(_config(root), "S001", "V1", {"CrPCr": cr, "Ins": other})

            np.testing.assert_allclose(_read(result), _vol([1, 2, 3, 4, 5, 6, 7, 8]))

    def test_explicit_preferred_met_argument_overrides_config_ref_met(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cr = _save(root / "cr.nii.gz", [1] * 8)
            ins = _save(root / "ins.nii.gz", [9] * 8)

            result = generate_reference(_config(root), "S001", "V1", {"CrPCr": cr, "Ins": ins}, preferred_met="Ins")

            np.testing.assert_allclose(_read(result), _vol([9] * 8))

    def test_nans_in_the_preferred_map_become_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cr = _save(root / "cr.nii.gz", [np.nan, 3, 3, 3, 3, 3, 3, 3])

            result = generate_reference(_config(root), "S001", "V1", {"CrPCr": cr})

            np.testing.assert_allclose(_read(result), _vol([0, 3, 3, 3, 3, 3, 3, 3]))

    def test_missing_preferred_metabolite_averages_the_others_over_nonzero_voxels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            a = _save(root / "a.nii.gz", [2, 0, 0, 0, 0, 0, 0, 0])
            b = _save(root / "b.nii.gz", [4, 8, 0, 0, 0, 0, 0, 0])

            result = generate_reference(_config(root, ref_met="Absent"), "S001", "V1", {"A": a, "B": b})

            # Voxel 0: both contribute -> (2+4)/2 = 3. Voxel 1: only b is
            # nonzero, so the zero must not drag the mean down -> 8, not 4.
            np.testing.assert_allclose(_read(result), _vol([3, 8, 0, 0, 0, 0, 0, 0]))

    def test_voxels_zero_in_every_map_stay_zero_rather_than_dividing_by_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            a = _save(root / "a.nii.gz", [0, 5, 0, 0, 0, 0, 0, 0])
            b = _save(root / "b.nii.gz", [0, 5, 0, 0, 0, 0, 0, 0])

            result = generate_reference(_config(root, ref_met="Absent"), "S001", "V1", {"A": a, "B": b})

            written = _read(result)
            np.testing.assert_allclose(written, _vol([0, 5, 0, 0, 0, 0, 0, 0]))
            self.assertTrue(np.all(np.isfinite(written)))

    def test_nans_are_zeroed_before_averaging_in_the_fallback_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            a = _save(root / "a.nii.gz", [np.nan, 4, 0, 0, 0, 0, 0, 0])
            b = _save(root / "b.nii.gz", [6, 4, 0, 0, 0, 0, 0, 0])

            result = generate_reference(_config(root, ref_met="Absent"), "S001", "V1", {"A": a, "B": b})

            # The NaN becomes 0, which is then excluded from the mean.
            np.testing.assert_allclose(_read(result), _vol([6, 4, 0, 0, 0, 0, 0, 0]))

    def test_no_metabolite_maps_at_all_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(ValueError, "No metabolite maps available"):
                generate_reference(_config(root, ref_met="Absent"), "S001", "V1", {})

    def test_cached_output_is_reused_unless_overwrite_is_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cr = _save(root / "cr.nii.gz", [1] * 8)
            config = _config(root)

            first = generate_reference(config, "S001", "V1", {"CrPCr": cr})
            _save(first, [7] * 8)
            second = generate_reference(config, "S001", "V1", {"CrPCr": cr})

            self.assertEqual(first, second)
            np.testing.assert_allclose(_read(second), _vol([7] * 8))

    def test_overwrite_regenerates_the_cached_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cr = _save(root / "cr.nii.gz", [1] * 8)

            first = generate_reference(_config(root), "S001", "V1", {"CrPCr": cr})
            _save(first, [7] * 8)
            second = generate_reference(_config(root, overwrite=True), "S001", "V1", {"CrPCr": cr})

            np.testing.assert_allclose(_read(second), _vol([1] * 8))

    def test_reference_preserves_the_source_affine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            affine = np.diag([3.0, 3.0, 3.5, 1.0])
            cr = _save(root / "cr.nii.gz", [1] * 8, affine=affine)

            result = generate_reference(_config(root), "S001", "V1", {"CrPCr": cr})

            np.testing.assert_allclose(nib.load(str(result)).affine, affine)


if __name__ == "__main__":
    unittest.main()

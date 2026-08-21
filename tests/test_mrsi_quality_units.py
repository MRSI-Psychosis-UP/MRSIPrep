import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import nibabel as nib
import numpy as np

from mrsiprep.mrsi.quality import _safe_mean, _safe_median, make_quality_masks


def _vol(values):
    """(2, 2, 2) volume; singleton dims would be squeezed away by load_3d_data."""
    return np.asarray(values, dtype=np.float32).reshape(2, 2, 2)


def _save(path: Path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(_vol(values), np.eye(4)), path)
    return path


def _read(path: Path):
    return np.asanyarray(nib.load(str(path)).dataobj)


def _config(root: Path, **overrides):
    base = dict(
        derivative_dir=root / "derivatives",
        overwrite=True,
        snr_min=5.0,
        linewidth_max=0.1,
        crlb_max=20.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _rows(summary: Path):
    with open(summary, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class SafeAggregateTests(unittest.TestCase):
    def test_none_data_returns_nan(self):
        self.assertTrue(np.isnan(_safe_mean(None, np.ones((2, 2, 2), dtype=bool))))
        self.assertTrue(np.isnan(_safe_median(None, np.ones((2, 2, 2), dtype=bool))))

    def test_all_false_mask_returns_nan_rather_than_raising(self):
        data = np.arange(8, dtype=np.float32).reshape(2, 2, 2)
        empty = np.zeros((2, 2, 2), dtype=bool)
        self.assertTrue(np.isnan(_safe_mean(data, empty)))
        self.assertTrue(np.isnan(_safe_median(data, empty)))

    def test_aggregates_only_the_masked_voxels(self):
        data = _vol([1, 2, 3, 4, 100, 100, 100, 100])
        mask = _vol([1, 1, 1, 1, 0, 0, 0, 0]).astype(bool)
        self.assertEqual(_safe_mean(data, mask), 2.5)
        self.assertEqual(_safe_median(data, mask), 2.5)

    def test_nans_inside_the_mask_are_ignored_not_propagated(self):
        data = _vol([np.nan, 2, 4, np.nan, 0, 0, 0, 0])
        mask = _vol([1, 1, 1, 1, 0, 0, 0, 0]).astype(bool)
        self.assertEqual(_safe_mean(data, mask), 3.0)
        self.assertEqual(_safe_median(data, mask), 3.0)

    def test_returns_plain_python_floats(self):
        data = _vol(range(8))
        mask = np.ones((2, 2, 2), dtype=bool)
        self.assertIsInstance(_safe_mean(data, mask), float)
        self.assertIsInstance(_safe_median(data, mask), float)


class MakeQualityMasksTests(unittest.TestCase):
    def test_mask_is_the_brain_mask_when_no_quality_maps_are_supplied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1, 1, 1, 1, 0, 0, 0, 0])
            met = _save(root / "met.nii.gz", [1] * 8)

            qcmasks, _ = make_quality_masks(_config(root), "S001", "V1", {"CrPCr": met}, {}, None, None, brain)

            np.testing.assert_array_equal(_read(qcmasks["CrPCr"]).astype(bool), _vol([1, 1, 1, 1, 0, 0, 0, 0]).astype(bool))

    def test_non_finite_metabolite_voxels_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1] * 8)
            met = _save(root / "met.nii.gz", [np.nan, np.inf, 1, 1, 1, 1, 1, 1])

            qcmasks, _ = make_quality_masks(_config(root), "S001", "V1", {"CrPCr": met}, {}, None, None, brain)

            np.testing.assert_array_equal(
                _read(qcmasks["CrPCr"]).astype(bool), _vol([0, 0, 1, 1, 1, 1, 1, 1]).astype(bool)
            )

    def test_snr_threshold_is_inclusive_at_the_minimum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1] * 8)
            met = _save(root / "met.nii.gz", [1] * 8)
            snr = _save(root / "snr.nii.gz", [4.9, 5.0, 5.1, 10, 10, 10, 10, 10])

            qcmasks, _ = make_quality_masks(_config(root, snr_min=5.0), "S001", "V1", {"CrPCr": met}, {}, snr, None, brain)

            np.testing.assert_array_equal(
                _read(qcmasks["CrPCr"]).astype(bool), _vol([0, 1, 1, 1, 1, 1, 1, 1]).astype(bool)
            )

    def test_linewidth_threshold_is_inclusive_at_the_maximum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1] * 8)
            met = _save(root / "met.nii.gz", [1] * 8)
            lw = _save(root / "lw.nii.gz", [0.09, 0.10, 0.11, 0, 0, 0, 0, 0])

            qcmasks, _ = make_quality_masks(
                _config(root, linewidth_max=0.10), "S001", "V1", {"CrPCr": met}, {}, None, lw, brain
            )

            np.testing.assert_array_equal(
                _read(qcmasks["CrPCr"]).astype(bool), _vol([1, 1, 0, 1, 1, 1, 1, 1]).astype(bool)
            )

    def test_crlb_threshold_is_inclusive_at_the_maximum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1] * 8)
            met = _save(root / "met.nii.gz", [1] * 8)
            crlb = _save(root / "crlb.nii.gz", [19, 20, 21, 0, 0, 0, 0, 0])

            qcmasks, _ = make_quality_masks(
                _config(root, crlb_max=20.0), "S001", "V1", {"CrPCr": met}, {"CrPCr": crlb}, None, None, brain
            )

            np.testing.assert_array_equal(
                _read(qcmasks["CrPCr"]).astype(bool), _vol([1, 1, 0, 1, 1, 1, 1, 1]).astype(bool)
            )

    def test_all_criteria_combine_as_an_intersection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1, 1, 1, 1, 1, 1, 1, 0])
            met = _save(root / "met.nii.gz", [1] * 8)
            snr = _save(root / "snr.nii.gz", [1, 10, 10, 10, 10, 10, 10, 10])
            lw = _save(root / "lw.nii.gz", [0, 1.0, 0, 0, 0, 0, 0, 0])
            crlb = _save(root / "crlb.nii.gz", [0, 0, 99, 0, 0, 0, 0, 0])

            qcmasks, _ = make_quality_masks(
                _config(root), "S001", "V1", {"CrPCr": met}, {"CrPCr": crlb}, snr, lw, brain
            )

            # Voxel 0 fails SNR, 1 fails linewidth, 2 fails CRLB, 7 is outside
            # the brain mask; the rest survive every criterion.
            np.testing.assert_array_equal(
                _read(qcmasks["CrPCr"]).astype(bool), _vol([0, 0, 0, 1, 1, 1, 1, 0]).astype(bool)
            )

    def test_missing_quality_map_files_are_treated_as_absent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1] * 8)
            met = _save(root / "met.nii.gz", [1] * 8)

            qcmasks, summary = make_quality_masks(
                _config(root),
                "S001",
                "V1",
                {"CrPCr": met},
                {"CrPCr": root / "absent-crlb.nii.gz"},
                root / "absent-snr.nii.gz",
                root / "absent-lw.nii.gz",
                brain,
            )

            self.assertTrue(np.all(_read(qcmasks["CrPCr"]).astype(bool)))
            row = _rows(summary)[0]
            for field in ("mean_snr", "mean_linewidth", "mean_crlb"):
                self.assertEqual(row[field], "")

    def test_crlb_is_applied_per_metabolite_not_globally(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1] * 8)
            met_a = _save(root / "a.nii.gz", [1] * 8)
            met_b = _save(root / "b.nii.gz", [1] * 8)
            crlb_a = _save(root / "crlb_a.nii.gz", [99, 0, 0, 0, 0, 0, 0, 0])

            qcmasks, _ = make_quality_masks(
                _config(root), "S001", "V1", {"A": met_a, "B": met_b}, {"A": crlb_a}, None, None, brain
            )

            # Only A has a CRLB map, so only A loses voxel 0.
            self.assertFalse(bool(_read(qcmasks["A"]).ravel()[0]))
            self.assertTrue(np.all(_read(qcmasks["B"]).astype(bool)))

    def test_one_mask_written_per_metabolite_as_uint8(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1] * 8)
            maps = {name: _save(root / f"{name}.nii.gz", [1] * 8) for name in ("CrPCr", "Ins", "NAA")}

            qcmasks, _ = make_quality_masks(_config(root), "S001", "V1", maps, {}, None, None, brain)

            self.assertEqual(set(qcmasks), set(maps))
            for path in qcmasks.values():
                self.assertTrue(path.exists())
                self.assertEqual(nib.load(str(path)).get_data_dtype(), np.uint8)

    def test_summary_has_one_row_per_metabolite_in_input_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1] * 8)
            maps = {name: _save(root / f"{name}.nii.gz", [1] * 8) for name in ("CrPCr", "Ins", "NAA")}

            _, summary = make_quality_masks(_config(root), "S001", "V1", maps, {}, None, None, brain)

            self.assertEqual([row["metabolite"] for row in _rows(summary)], ["CrPCr", "Ins", "NAA"])

    def test_n_total_voxels_counts_the_brain_mask_not_the_qc_mask(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1, 1, 1, 1, 1, 0, 0, 0])
            met = _save(root / "met.nii.gz", [1] * 8)
            # Fails CRLB everywhere, so the QC mask is empty while the brain
            # mask still has 5 voxels.
            crlb = _save(root / "crlb.nii.gz", [99] * 8)

            _, summary = make_quality_masks(
                _config(root), "S001", "V1", {"CrPCr": met}, {"CrPCr": crlb}, None, None, brain
            )

            self.assertEqual(_rows(summary)[0]["n_total_voxels"], "5")

    def test_summary_statistics_are_computed_over_surviving_voxels_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1] * 8)
            met = _save(root / "met.nii.gz", [1] * 8)
            # Voxel 0 is dropped for low SNR; its 1.0 must not enter the mean.
            snr = _save(root / "snr.nii.gz", [1, 10, 10, 10, 10, 10, 10, 10])

            _, summary = make_quality_masks(
                _config(root, snr_min=5.0), "S001", "V1", {"CrPCr": met}, {}, snr, None, brain
            )

            row = _rows(summary)[0]
            self.assertAlmostEqual(float(row["mean_snr"]), 10.0)
            self.assertAlmostEqual(float(row["median_snr"]), 10.0)

    def test_empty_qc_mask_yields_blank_statistics_without_raising(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [0] * 8)
            met = _save(root / "met.nii.gz", [1] * 8)
            snr = _save(root / "snr.nii.gz", [10] * 8)

            _, summary = make_quality_masks(_config(root), "S001", "V1", {"CrPCr": met}, {}, snr, None, brain)

            row = _rows(summary)[0]
            self.assertEqual(row["n_total_voxels"], "0")
            self.assertEqual(row["mean_snr"], "")

    def test_no_metabolites_writes_an_empty_summary_and_no_masks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brain = _save(root / "brain.nii.gz", [1] * 8)

            qcmasks, summary = make_quality_masks(_config(root), "S001", "V1", {}, {}, None, None, brain)

            self.assertEqual(qcmasks, {})
            self.assertTrue(summary.exists())
            self.assertEqual(_rows(summary), [])


if __name__ == "__main__":
    unittest.main()

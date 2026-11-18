import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import nibabel as nib
import numpy as np

from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.parcellation.extraction import (
    _load_optional,
    _masked_mean,
    extract_regional_metabolites,
)


def _vol(values):
    """(2, 2, 2) volume; singleton dims would be squeezed away by load_3d_data."""
    return np.asarray(values, dtype=np.float32).reshape(2, 2, 2)


def _save(path: Path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(_vol(values), np.eye(4)), path)
    return path


def _labels(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _read(path: Path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _config(root: Path):
    return SimpleNamespace(derivative_dir=root / "derivatives")


class LoadOptionalTests(unittest.TestCase):
    def test_none_path_returns_none(self):
        self.assertIsNone(_load_optional(None))

    def test_missing_file_returns_none_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(_load_optional(Path(tmpdir) / "absent.nii.gz"))

    def test_existing_file_is_loaded_as_an_array(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _save(Path(tmpdir) / "x.nii.gz", range(8))
            np.testing.assert_allclose(_load_optional(path), _vol(range(8)))

    def test_accepts_a_string_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _save(Path(tmpdir) / "x.nii.gz", [1] * 8)
            self.assertIsNotNone(_load_optional(str(path)))


class MaskedMeanTests(unittest.TestCase):
    def test_none_data_returns_nan(self):
        self.assertTrue(np.isnan(_masked_mean(None, np.ones((2, 2, 2), dtype=bool))))

    def test_empty_mask_returns_nan(self):
        self.assertTrue(np.isnan(_masked_mean(_vol(range(8)), np.zeros((2, 2, 2), dtype=bool))))

    def test_averages_only_masked_voxels_ignoring_nans(self):
        data = _vol([2, 4, np.nan, 100, 100, 100, 100, 100])
        mask = _vol([1, 1, 1, 0, 0, 0, 0, 0]).astype(bool)
        self.assertEqual(_masked_mean(data, mask), 3.0)


class ExtractRegionalMetabolitesTests(unittest.TestCase):
    def _parcels(self, root, atlas_values, label_rows, atlas_name="testatlas", scale=None):
        return ParcellationResult(
            atlas_mrsi=_save(root / "atlas.nii.gz", atlas_values),
            labels=_labels(root / "labels.tsv", label_rows),
            atlas_name=atlas_name,
            scale=scale,
        )

    def test_one_row_per_parcel_metabolite_pair(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(
                root,
                [1, 1, 2, 2, 0, 0, 0, 0],
                [{"parcel_id": 1, "parcel_name": "A"}, {"parcel_id": 2, "parcel_name": "B"}],
            )
            maps = {m: _save(root / f"{m}.nii.gz", [1] * 8) for m in ("CrPCr", "Ins")}

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", maps, parcels, {}, None, None, {}, {}
            )

            rows = _read(out)
            self.assertEqual(len(rows), 4)
            self.assertEqual({(r["parcel_id"], r["metabolite"]) for r in rows},
                             {("1", "CrPCr"), ("1", "Ins"), ("2", "CrPCr"), ("2", "Ins")})

    def test_parcels_absent_from_the_atlas_volume_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(
                root,
                [1] * 8,
                [{"parcel_id": 1, "parcel_name": "Present"}, {"parcel_id": 99, "parcel_name": "Absent"}],
            )

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": _save(root / "m.nii.gz", [1] * 8)},
                parcels, {}, None, None, {}, {},
            )

            self.assertEqual([r["parcel_id"] for r in _read(out)], ["1"])

    def test_summary_statistics_are_computed_over_the_parcel_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1, 1, 0, 0, 0, 0, 0, 0], [{"parcel_id": 1, "parcel_name": "A"}])
            # Parcel covers voxels 0-1 (values 2 and 4); the rest must not count.
            met = _save(root / "m.nii.gz", [2, 4, 1000, 1000, 1000, 1000, 1000, 1000])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": met}, parcels, {}, None, None, {}, {}
            )

            row = _read(out)[0]
            self.assertAlmostEqual(float(row["mean"]), 3.0)
            self.assertAlmostEqual(float(row["median"]), 3.0)
            self.assertAlmostEqual(float(row["std"]), 1.0)
            self.assertEqual(row["n_voxels"], "2")

    def test_qc_mask_further_restricts_the_parcel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1, 1, 1, 1, 0, 0, 0, 0], [{"parcel_id": 1, "parcel_name": "A"}])
            met = _save(root / "m.nii.gz", [1, 1, 5, 5, 0, 0, 0, 0])
            qc = _save(root / "qc.nii.gz", [0, 0, 1, 1, 0, 0, 0, 0])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": met}, parcels, {"CrPCr": qc}, None, None, {}, {}
            )

            row = _read(out)[0]
            self.assertEqual(row["n_voxels"], "2")
            self.assertAlmostEqual(float(row["mean"]), 5.0)

    def test_coverage_is_the_kept_fraction_of_the_parcel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1, 1, 1, 1, 0, 0, 0, 0], [{"parcel_id": 1, "parcel_name": "A"}])
            met = _save(root / "m.nii.gz", [1] * 8)
            qc = _save(root / "qc.nii.gz", [1, 0, 0, 0, 0, 0, 0, 0])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": met}, parcels, {"CrPCr": qc}, None, None, {}, {}
            )

            self.assertAlmostEqual(float(_read(out)[0]["coverage"]), 0.25)

    def test_non_finite_metabolite_voxels_are_excluded_even_without_a_qc_mask(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1, 1, 1, 1, 0, 0, 0, 0], [{"parcel_id": 1, "parcel_name": "A"}])
            met = _save(root / "m.nii.gz", [np.nan, np.inf, 3, 3, 0, 0, 0, 0])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": met}, parcels, {}, None, None, {}, {}
            )

            row = _read(out)[0]
            self.assertEqual(row["n_voxels"], "2")
            self.assertAlmostEqual(float(row["mean"]), 3.0)

    def test_weighted_mean_uses_snr_as_weights(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1, 1, 0, 0, 0, 0, 0, 0], [{"parcel_id": 1, "parcel_name": "A"}])
            met = _save(root / "m.nii.gz", [10, 20, 0, 0, 0, 0, 0, 0])
            snr = _save(root / "snr.nii.gz", [1, 3, 0, 0, 0, 0, 0, 0])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": met}, parcels, {}, snr, None, {}, {}
            )

            # (10*1 + 20*3) / 4 = 17.5, distinct from the unweighted 15.
            row = _read(out)[0]
            self.assertAlmostEqual(float(row["weighted_mean"]), 17.5)
            self.assertAlmostEqual(float(row["mean"]), 15.0)

    def test_weighted_mean_falls_back_to_uniform_weights_without_snr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1, 1, 0, 0, 0, 0, 0, 0], [{"parcel_id": 1, "parcel_name": "A"}])
            met = _save(root / "m.nii.gz", [10, 20, 0, 0, 0, 0, 0, 0])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": met}, parcels, {}, None, None, {}, {}
            )

            row = _read(out)[0]
            self.assertAlmostEqual(float(row["weighted_mean"]), 15.0)

    def test_all_zero_weights_leave_weighted_mean_blank_instead_of_dividing_by_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1, 1, 0, 0, 0, 0, 0, 0], [{"parcel_id": 1, "parcel_name": "A"}])
            met = _save(root / "m.nii.gz", [10, 20, 0, 0, 0, 0, 0, 0])
            snr = _save(root / "snr.nii.gz", [0, 0, 0, 0, 0, 0, 0, 0])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": met}, parcels, {}, snr, None, {}, {}
            )

            row = _read(out)[0]
            self.assertEqual(row["weighted_mean"], "")
            self.assertAlmostEqual(float(row["mean"]), 15.0)

    def test_nan_snr_weights_are_zeroed_rather_than_poisoning_the_average(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1, 1, 0, 0, 0, 0, 0, 0], [{"parcel_id": 1, "parcel_name": "A"}])
            met = _save(root / "m.nii.gz", [10, 20, 0, 0, 0, 0, 0, 0])
            snr = _save(root / "snr.nii.gz", [np.nan, 2, 0, 0, 0, 0, 0, 0])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": met}, parcels, {}, snr, None, {}, {}
            )

            # The NaN weight becomes 0, so only voxel 1 contributes.
            self.assertAlmostEqual(float(_read(out)[0]["weighted_mean"]), 20.0)

    def test_tissue_fractions_are_reported_per_parcel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1, 1, 0, 0, 0, 0, 0, 0], [{"parcel_id": 1, "parcel_name": "A"}])
            met = _save(root / "m.nii.gz", [1] * 8)
            tissue = {
                "GM": _save(root / "gm.nii.gz", [0.8, 0.6, 0, 0, 0, 0, 0, 0]),
                "WM": _save(root / "wm.nii.gz", [0.2, 0.4, 0, 0, 0, 0, 0, 0]),
                "CSF": _save(root / "csf.nii.gz", [0.0, 0.0, 0, 0, 0, 0, 0, 0]),
            }

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": met}, parcels, {}, None, None, {}, tissue
            )

            row = _read(out)[0]
            self.assertAlmostEqual(float(row["mean_gm_fraction"]), 0.7, places=5)
            self.assertAlmostEqual(float(row["mean_wm_fraction"]), 0.3, places=5)
            self.assertAlmostEqual(float(row["mean_csf_fraction"]), 0.0)

    def test_crlb_is_looked_up_per_metabolite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1, 1, 0, 0, 0, 0, 0, 0], [{"parcel_id": 1, "parcel_name": "A"}])
            maps = {m: _save(root / f"{m}.nii.gz", [1] * 8) for m in ("CrPCr", "Ins")}
            crlb = {"CrPCr": _save(root / "crlb.nii.gz", [5, 7, 0, 0, 0, 0, 0, 0])}

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", maps, parcels, {}, None, None, crlb, {}
            )

            by_met = {r["metabolite"]: r for r in _read(out)}
            self.assertAlmostEqual(float(by_met["CrPCr"]["mean_crlb"]), 6.0)
            self.assertEqual(by_met["Ins"]["mean_crlb"], "")

    def test_optional_maps_that_do_not_exist_are_reported_blank(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1] * 8, [{"parcel_id": 1, "parcel_name": "A"}])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": _save(root / "m.nii.gz", [1] * 8)},
                parcels, {}, root / "no-snr.nii.gz", root / "no-lw.nii.gz", {}, {},
            )

            row = _read(out)[0]
            self.assertEqual(row["mean_snr"], "")
            self.assertEqual(row["mean_linewidth"], "")

    def test_subject_and_session_are_written_with_bids_prefixes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1] * 8, [{"parcel_id": 1, "parcel_name": "A"}])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": _save(root / "m.nii.gz", [1] * 8)},
                parcels, {}, None, None, {}, {},
            )

            row = _read(out)[0]
            self.assertEqual(row["subject"], "sub-S001")
            self.assertEqual(row["session"], "ses-V1")

    def test_sessionless_recording_leaves_the_session_column_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1] * 8, [{"parcel_id": 1, "parcel_name": "A"}])

            out = extract_regional_metabolites(
                _config(root), "S001", None, {"CrPCr": _save(root / "m.nii.gz", [1] * 8)},
                parcels, {}, None, None, {}, {},
            )

            self.assertEqual(_read(out)[0]["session"], "")

    def test_atlas_name_and_scale_are_carried_into_every_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(
                root, [1] * 8, [{"parcel_id": 1, "parcel_name": "A"}], atlas_name="chimera-LFMIHIFIS", scale="3"
            )

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": _save(root / "m.nii.gz", [1] * 8)},
                parcels, {}, None, None, {}, {},
            )

            row = _read(out)[0]
            self.assertEqual(row["atlas"], "chimera-LFMIHIFIS")
            self.assertEqual(row["scale"], "3")

    def test_absent_scale_is_written_as_empty_not_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1] * 8, [{"parcel_id": 1, "parcel_name": "A"}], scale=None)

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": _save(root / "m.nii.gz", [1] * 8)},
                parcels, {}, None, None, {}, {},
            )

            self.assertEqual(_read(out)[0]["scale"], "")

    def test_parcel_name_and_hemisphere_come_from_the_label_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(
                root, [1] * 8, [{"parcel_id": 1, "parcel_name": "Precuneus", "hemisphere": "L"}]
            )

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": _save(root / "m.nii.gz", [1] * 8)},
                parcels, {}, None, None, {}, {},
            )

            row = _read(out)[0]
            self.assertEqual(row["parcel_name"], "Precuneus")
            self.assertEqual(row["hemisphere"], "L")

    def test_hemisphere_defaults_to_na_when_the_label_table_omits_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parcels = self._parcels(root, [1] * 8, [{"parcel_id": 1, "parcel_name": "A"}])

            out = extract_regional_metabolites(
                _config(root), "S001", "V1", {"CrPCr": _save(root / "m.nii.gz", [1] * 8)},
                parcels, {}, None, None, {}, {},
            )

            self.assertEqual(_read(out)[0]["hemisphere"], "NA")


if __name__ == "__main__":
    unittest.main()

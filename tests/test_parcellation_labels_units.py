import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from mrsiprep.parcellation.labels import (
    copy_labels,
    infer_hemisphere,
    normalize_label_table,
    write_labels,
)


def _read(path):
    # keep_default_na=False: "NA" is a real hemisphere value here, not a
    # missing-value marker, and pandas would otherwise read it back as NaN.
    return pd.read_csv(path, sep="\t", keep_default_na=False)


class InferHemisphereTests(unittest.TestCase):
    def test_left_markers(self):
        for name in ("lh-precuneus", "Left-Thalamus", "ctx-lh-superiorfrontal", "CTX-L-insula"):
            self.assertEqual(infer_hemisphere(name), "L", msg=name)

    def test_right_markers(self):
        for name in ("rh-precuneus", "Right-Thalamus", "ctx-rh-superiorfrontal", "CTX-R-insula"):
            self.assertEqual(infer_hemisphere(name), "R", msg=name)

    def test_unsided_structures_are_na(self):
        for name in ("brain-stem", "midbrain", "corpus-callosum", "3rd-ventricle"):
            self.assertEqual(infer_hemisphere(name), "NA", msg=name)

    def test_matching_is_case_insensitive(self):
        self.assertEqual(infer_hemisphere("LEFT-Amygdala"), "L")
        self.assertEqual(infer_hemisphere("RIGHT-Amygdala"), "R")

    def test_left_is_checked_before_right(self):
        # A name carrying both markers resolves to L; documents the ordering
        # rather than leaving it to chance.
        self.assertEqual(infer_hemisphere("left-to-right-tract"), "L")

    def test_non_string_input_is_coerced(self):
        self.assertEqual(infer_hemisphere(42), "NA")


class WriteLabelsTests(unittest.TestCase):
    def test_writes_one_row_per_index_with_expected_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "labels.tsv"

            write_labels([1, 2], ["lh-precuneus", "brain-stem"], out)

            df = _read(out)
            self.assertEqual(list(df.columns), ["parcel_id", "parcel_name", "hemisphere", "color"])
            self.assertEqual(list(df["parcel_id"]), [1, 2])
            self.assertEqual(list(df["parcel_name"]), ["lh-precuneus", "brain-stem"])

    def test_hemisphere_is_inferred_from_each_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "labels.tsv"

            write_labels([1, 2, 3], ["lh-a", "rh-b", "brain-stem"], out)

            self.assertEqual(list(_read(out)["hemisphere"]), ["L", "R", "NA"])

    def test_byte_labels_are_decoded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "labels.tsv"

            write_labels([1], [b"lh-precuneus"], out)

            row = _read(out).iloc[0]
            self.assertEqual(row["parcel_name"], "lh-precuneus")
            self.assertEqual(row["hemisphere"], "L")

    def test_numpy_indices_are_written_as_plain_ints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "labels.tsv"

            write_labels(np.array([7, 8]), ["a", "b"], out)

            self.assertEqual(list(_read(out)["parcel_id"]), [7, 8])

    def test_color_is_a_six_digit_hex_string(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "labels.tsv"

            write_labels(range(20), [f"p{i}" for i in range(20)], out)

            for color in _read(out)["color"]:
                self.assertRegex(color, r"^#[0-9a-f]{6}$")

    def test_extra_labels_beyond_the_indices_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "labels.tsv"

            write_labels([1], ["a", "b", "c"], out)

            self.assertEqual(len(_read(out)), 1)

    def test_parent_directories_are_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "deep" / "nested" / "labels.tsv"

            result = write_labels([1], ["a"], out)

            self.assertTrue(result.exists())

    def test_returns_the_output_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "labels.tsv"
            self.assertEqual(write_labels([1], ["a"], out), out)


class NormalizeLabelTableTests(unittest.TestCase):
    def _write(self, path, frame: dict):
        pd.DataFrame(frame).to_csv(path, sep="\t", index=False)
        return path

    def test_index_and_name_columns_are_renamed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._write(Path(tmpdir) / "in.tsv", {"index": [1, 2], "name": ["lh-a", "rh-b"]})
            out = Path(tmpdir) / "out.tsv"

            normalize_label_table(src, out)

            df = _read(out)
            self.assertIn("parcel_id", df.columns)
            self.assertIn("parcel_name", df.columns)

    def test_hemisphere_is_derived_when_absent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._write(Path(tmpdir) / "in.tsv", {"index": [1, 2], "name": ["lh-a", "rh-b"]})
            out = Path(tmpdir) / "out.tsv"

            normalize_label_table(src, out)

            self.assertEqual(list(_read(out)["hemisphere"]), ["L", "R"])

    def test_existing_hemisphere_column_is_preserved_not_recomputed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # "lh-a" would infer L, but an explicit curated value must win.
            src = self._write(
                Path(tmpdir) / "in.tsv", {"parcel_id": [1], "parcel_name": ["lh-a"], "hemisphere": ["R"]}
            )
            out = Path(tmpdir) / "out.tsv"

            normalize_label_table(src, out)

            self.assertEqual(list(_read(out)["hemisphere"]), ["R"])

    def test_missing_parcel_name_falls_back_to_the_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._write(Path(tmpdir) / "in.tsv", {"parcel_id": [11, 22]})
            out = Path(tmpdir) / "out.tsv"

            normalize_label_table(src, out)

            self.assertEqual(list(_read(out)["parcel_name"].astype(str)), ["11", "22"])

    def test_already_normalized_table_written_in_place_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._write(
                Path(tmpdir) / "in.tsv", {"parcel_id": [1], "parcel_name": ["a"], "hemisphere": ["NA"]}
            )
            before = src.read_text(encoding="utf-8")

            result = normalize_label_table(src)

            self.assertEqual(result, src)
            self.assertEqual(src.read_text(encoding="utf-8"), before)

    def test_in_place_normalization_rewrites_a_legacy_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._write(Path(tmpdir) / "in.tsv", {"index": [1], "name": ["lh-a"]})

            result = normalize_label_table(src)

            self.assertEqual(result, src)
            df = _read(src)
            self.assertIn("parcel_id", df.columns)
            self.assertEqual(list(df["hemisphere"]), ["L"])

    def test_source_is_not_modified_when_writing_elsewhere(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._write(Path(tmpdir) / "in.tsv", {"index": [1], "name": ["lh-a"]})
            before = src.read_text(encoding="utf-8")
            out = Path(tmpdir) / "nested" / "out.tsv"

            normalize_label_table(src, out)

            self.assertEqual(src.read_text(encoding="utf-8"), before)
            self.assertTrue(out.exists())

    def test_returns_the_output_path_when_one_is_given(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._write(Path(tmpdir) / "in.tsv", {"index": [1], "name": ["a"]})
            out = Path(tmpdir) / "out.tsv"
            self.assertEqual(normalize_label_table(src, out), out)


class CopyLabelsTests(unittest.TestCase):
    def test_copies_and_normalizes_in_one_step(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src.tsv"
            pd.DataFrame({"index": [1, 2], "name": ["lh-a", "rh-b"]}).to_csv(src, sep="\t", index=False)
            dst = root / "nested" / "dst.tsv"

            result = copy_labels(src, dst)

            self.assertEqual(result, dst)
            df = _read(dst)
            self.assertIn("parcel_id", df.columns)
            self.assertEqual(list(df["hemisphere"]), ["L", "R"])

    def test_source_is_left_in_its_original_legacy_form(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src.tsv"
            pd.DataFrame({"index": [1], "name": ["lh-a"]}).to_csv(src, sep="\t", index=False)
            before = src.read_text(encoding="utf-8")

            copy_labels(src, root / "dst.tsv")

            self.assertEqual(src.read_text(encoding="utf-8"), before)

    def test_missing_source_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(FileNotFoundError):
                copy_labels(root / "absent.tsv", root / "dst.tsv")

    def test_accepts_string_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src.tsv"
            pd.DataFrame({"parcel_id": [1], "parcel_name": ["a"]}).to_csv(src, sep="\t", index=False)

            result = copy_labels(str(src), str(root / "dst.tsv"))

            self.assertTrue(Path(result).exists())


if __name__ == "__main__":
    unittest.main()

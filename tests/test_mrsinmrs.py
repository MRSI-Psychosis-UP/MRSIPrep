import json
import tempfile
import unittest
from pathlib import Path

from mrsiprep.io.mrsinmrs import load_mrsinmrs, resolve_mrsinmrs


class MRSinMRSTests(unittest.TestCase):
    def test_load_mrsinmrs_returns_none_when_file_absent(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(load_mrsinmrs(td))

    def test_load_mrsinmrs_raises_on_malformed_json(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "mrsinmrs.json").write_text("{not valid json")
            with self.assertRaises(ValueError):
                load_mrsinmrs(td)

    def test_load_mrsinmrs_rejects_unsupported_top_level_keys(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "mrsinmrs.json").write_text(json.dumps({"Unsupported": {}}))
            with self.assertRaises(ValueError):
                load_mrsinmrs(td)

    def test_resolve_mrsinmrs_merges_common_and_recording_override(self):
        parsed = {
            "CommonMetadata": {"FieldStrength_T": 3, "Sequence": "ECCENTRIC"},
            "Recordings": [
                {"sub": "01", "ses": "01"},
                {"sub": "02", "ses": "01", "FieldStrength_T": 7},
            ],
        }
        resolved_default = resolve_mrsinmrs(parsed, "01", "01")
        self.assertEqual(resolved_default["FieldStrength_T"], 3)
        self.assertEqual(resolved_default["Sequence"], "ECCENTRIC")

        resolved_override = resolve_mrsinmrs(parsed, "02", "01")
        self.assertEqual(resolved_override["FieldStrength_T"], 7)
        self.assertEqual(resolved_override["Sequence"], "ECCENTRIC")

    def test_resolve_mrsinmrs_subject_only_entry_applies_to_all_sessions(self):
        parsed = {
            "CommonMetadata": {"FieldStrength_T": 3},
            "Recordings": [{"sub": "01", "TR_ms": 457}],
        }
        resolved = resolve_mrsinmrs(parsed, "01", "02")
        self.assertEqual(resolved["TR_ms"], 457)

    def test_resolve_mrsinmrs_handles_sub_ses_prefixes(self):
        parsed = {"CommonMetadata": {}, "Recordings": [{"sub": "sub-01", "ses": "ses-01", "TR_ms": 400}]}
        resolved = resolve_mrsinmrs(parsed, "01", "01")
        self.assertEqual(resolved["TR_ms"], 400)

    def test_resolve_mrsinmrs_returns_none_when_parsed_is_none(self):
        self.assertIsNone(resolve_mrsinmrs(None, "01", "01"))

    def test_resolve_mrsinmrs_returns_none_when_no_data_applies(self):
        parsed = {"CommonMetadata": {}, "Recordings": []}
        self.assertIsNone(resolve_mrsinmrs(parsed, "01", "01"))


if __name__ == "__main__":
    unittest.main()

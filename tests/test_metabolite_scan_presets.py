import json
import tempfile
import unittest
from pathlib import Path

from mrsiprep.config import metabolite_scan_presets as P


def _write(data) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, handle)
    handle.close()
    return Path(handle.name)


class LoadMetaboliteScanPresetsTests(unittest.TestCase):
    def test_shipped_file_loads(self):
        table = P.load_metabolite_scan_presets()
        self.assertIn("1H", table)
        self.assertIn("31P", table)

    def test_rejects_missing_nuclei_list(self):
        path = _write({"scope": "x"})
        with self.assertRaises(ValueError):
            P.load_metabolite_scan_presets(path)

    def test_rejects_entry_with_no_nucleus_name(self):
        path = _write({"nuclei": [{"metabolites": []}]})
        with self.assertRaises(ValueError):
            P.load_metabolite_scan_presets(path)


class ScanCandidatesTests(unittest.TestCase):
    def test_1h_includes_metabolites_and_combined_signals(self):
        candidates = P.scan_candidates("1H")
        self.assertIn("NAA", candidates)
        self.assertIn("Glu", candidates)
        self.assertIn("tCr", candidates)  # combined_signals entry

    def test_31p_candidates_present(self):
        candidates = P.scan_candidates("31P")
        self.assertIn("ATP", candidates)
        self.assertIn("PCr", candidates)

    def test_unknown_nucleus_returns_empty_list_not_error(self):
        self.assertEqual(P.scan_candidates("not-a-real-nucleus"), [])

    def test_candidates_are_deduplicated_and_sorted(self):
        candidates = P.scan_candidates("1H")
        self.assertEqual(candidates, sorted(set(candidates)))


class AvailablePresetNucleiTests(unittest.TestCase):
    def test_lists_shipped_nuclei(self):
        self.assertEqual(P.available_preset_nuclei(), sorted(P.available_preset_nuclei()))
        self.assertIn("1H", P.available_preset_nuclei())
        self.assertIn("13C", P.available_preset_nuclei())
        self.assertIn("31P", P.available_preset_nuclei())

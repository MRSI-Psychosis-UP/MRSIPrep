"""MRSI PVC tab sections.

The contract that matters: the montage must be drawn at the *same* slices as
the MRSI Raw QC tab, since the whole point of the tab is flipping between the
two, and a missing map must not take the tab down with it.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from mrsiprep.reports.mrsi_pvc_overview import build_mrsi_pvc_sections

MODULE = "mrsiprep.reports.mrsi_pvc_overview"


class BuildMrsiPvcSectionsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.config = SimpleNamespace(derivative_dir=self.tmp / "derivatives")
        self.volume = np.ones((4, 4, 6), dtype=np.float32)

    def _maps(self, *names):
        maps = {}
        for name in names:
            path = self.tmp / f"{name}.nii.gz"
            path.write_bytes(b"x")
            maps[name] = path
        return maps

    def test_no_maps_reports_it_rather_than_returning_nothing(self):
        sections = build_mrsi_pvc_sections(self.config, "01", "01", {})
        self.assertEqual(len(sections), 1)
        self.assertIn("No partial-volume-corrected maps", sections[0][1])

    def test_one_section_per_metabolite_plus_the_explanatory_header(self):
        maps = self._maps("CrPCr", "NAANAAG")
        with patch(f"{MODULE}.load_canonical_data", return_value=self.volume), patch(
            f"{MODULE}._render_slice_montage"
        ) as render:
            sections = build_mrsi_pvc_sections(self.config, "01", "01", maps)
        headings = [heading for heading, _body in sections]
        self.assertEqual(headings[0], "Partial-volume correction")
        self.assertEqual(headings[1:], ["Metabolite: CrPCr", "Metabolite: NAANAAG"])
        self.assertEqual(render.call_count, 2)

    def test_says_it_matches_the_raw_qc_slices(self):
        maps = self._maps("CrPCr")
        with patch(f"{MODULE}.load_canonical_data", return_value=self.volume), patch(
            f"{MODULE}._render_slice_montage"
        ):
            sections = build_mrsi_pvc_sections(self.config, "01", "01", maps)
        self.assertIn("same slices as the MRSI Raw QC tab", sections[0][1])

    def test_reference_map_drives_the_intensity_scale(self):
        """The pre-PVC map is passed as the scaling reference so a metabolite
        whose scale PVC changed is still readable rather than saturating."""
        pvc = self._maps("CrPCr")
        reference = {"CrPCr": self.tmp / "ref.nii.gz"}
        reference["CrPCr"].write_bytes(b"x")
        loaded = {}

        def _load(path):
            loaded[Path(path).name] = True
            return self.volume

        with patch(f"{MODULE}.load_canonical_data", side_effect=_load), patch(
            f"{MODULE}._render_slice_montage"
        ) as render:
            build_mrsi_pvc_sections(self.config, "01", "01", pvc, reference)
        self.assertIn("ref.nii.gz", loaded)
        self.assertEqual(render.call_args.kwargs["label"], "CrPCr (PVC)")

    def test_falls_back_to_the_pvc_map_when_no_reference_is_given(self):
        maps = self._maps("CrPCr")
        with patch(f"{MODULE}.load_canonical_data", return_value=self.volume), patch(
            f"{MODULE}._render_slice_montage"
        ) as render:
            build_mrsi_pvc_sections(self.config, "01", "01", maps, None)
        render.assert_called_once()

    def test_missing_map_on_disk_is_skipped_not_fatal(self):
        maps = {"CrPCr": self.tmp / "absent.nii.gz"}
        with patch(f"{MODULE}.load_canonical_data", return_value=self.volume), patch(
            f"{MODULE}._render_slice_montage"
        ) as render:
            sections = build_mrsi_pvc_sections(self.config, "01", "01", maps)
        render.assert_not_called()
        self.assertEqual(len(sections), 1)  # header only


if __name__ == "__main__":
    unittest.main()

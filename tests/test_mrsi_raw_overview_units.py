"""Tests for reports/mrsi_raw_overview.py's orchestration and edge-case
rendering branches. _center_weighted_indices/_equally_spaced_slices and
the vmax-from-preproc-not-raw scaling behavior are already covered by
test_mrsi_raw_overview.py; these target build_mrsi_raw_qc_sections
(untested) and two _render_slice_montage branches its spike-focused
tests don't reach (a single-slice montage, and an all-non-finite
preproc map falling back to the raw volume's own max).
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from mrsiprep.reports.mrsi_raw_overview import _render_slice_montage, build_mrsi_raw_qc_sections


class BuildMrsiRawQcSectionsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.config = SimpleNamespace(derivative_dir=self.tmp / "derivatives" / "mrsiprep")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_no_raw_maps_returns_placeholder_section(self):
        sections = build_mrsi_raw_qc_sections(self.config, "01", "01", {}, {})
        self.assertEqual(len(sections), 1)
        heading, body = sections[0]
        self.assertEqual(heading, "Raw metabolite maps")
        self.assertIn("No raw MRSI metabolite maps available", body)

    def test_one_section_per_metabolite_sorted_by_name(self):
        raw_maps = {"GluGln": Path("glugln.nii.gz"), "CrPCr": Path("crpcr.nii.gz")}
        fake_data = np.ones((4, 4, 4), dtype=np.float32)
        with patch("mrsiprep.reports.mrsi_raw_overview.load_canonical_data", return_value=fake_data), patch(
            "mrsiprep.reports.mrsi_raw_overview._render_slice_montage"
        ) as render:
            sections = build_mrsi_raw_qc_sections(self.config, "01", "01", raw_maps, {})

        self.assertEqual([heading for heading, _ in sections], ["Metabolite: CrPCr", "Metabolite: GluGln"])
        self.assertEqual(render.call_count, 2)
        for _heading, body in sections:
            self.assertIn("<img src=", body)

    def test_falls_back_to_raw_data_when_no_preproc_map_for_metabolite(self):
        raw_maps = {"CrPCr": Path("crpcr.nii.gz")}
        raw_data = np.full((4, 4, 4), 7.0, dtype=np.float32)
        with patch("mrsiprep.reports.mrsi_raw_overview.load_canonical_data", return_value=raw_data) as load, patch(
            "mrsiprep.reports.mrsi_raw_overview._render_slice_montage"
        ) as render:
            build_mrsi_raw_qc_sections(self.config, "01", "01", raw_maps, preproc_maps={})

        load.assert_called_once()  # only the raw map is loaded; no preproc lookup attempted
        passed_volume, passed_preproc = render.call_args[0][0], render.call_args[0][1]
        self.assertIs(passed_volume, raw_data)
        self.assertIs(passed_preproc, raw_data)

    def test_uses_preproc_map_for_color_scale_when_present(self):
        raw_maps = {"CrPCr": Path("crpcr.nii.gz")}
        preproc_maps = {"CrPCr": Path("crpcr_filtered.nii.gz")}
        raw_data = np.full((4, 4, 4), 999.0, dtype=np.float32)
        preproc_data = np.full((4, 4, 4), 5.0, dtype=np.float32)
        with patch("mrsiprep.reports.mrsi_raw_overview.load_canonical_data", side_effect=[raw_data, preproc_data]), patch(
            "mrsiprep.reports.mrsi_raw_overview._render_slice_montage"
        ) as render:
            build_mrsi_raw_qc_sections(self.config, "01", "01", raw_maps, preproc_maps)

        passed_volume, passed_preproc = render.call_args[0][0], render.call_args[0][1]
        self.assertIs(passed_volume, raw_data)
        self.assertIs(passed_preproc, preproc_data)


class RenderSliceMontageEdgeCaseTests(unittest.TestCase):
    def test_single_usable_slice_still_renders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "montage.png"
            # Signal only nonzero in the very center slice along axis 2, so
            # _equally_spaced_slices' emptiness skip leaves exactly one plane.
            volume = np.zeros((6, 6, 6), dtype=np.float32)
            volume[:, :, 3] = 1.0
            result = _render_slice_montage(volume, volume, out_path, label="CrPCr")
            self.assertEqual(result, out_path)
            self.assertTrue(out_path.exists())

    def test_falls_back_to_raw_max_when_preproc_has_no_finite_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "montage.png"
            volume = np.ones((6, 6, 6), dtype=np.float32) * 3.0
            preproc_all_nan = np.full((6, 6, 6), np.nan, dtype=np.float32)
            # Must not raise despite an entirely non-finite preproc map.
            result = _render_slice_montage(volume, preproc_all_nan, out_path, label="CrPCr")
            self.assertTrue(result.exists())


if __name__ == "__main__":
    unittest.main()

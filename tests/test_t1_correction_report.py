import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.reports.t1_correction import METABOLITE_COLORMAPS, build_t1_correction_qc_sections


class BuildT1CorrectionQcSectionsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.config = SimpleNamespace(derivative_dir=self.tmp / "derivatives" / "mrsiprep")
        self._patches = [
            patch("mrsiprep.reports.t1_correction.load_canonical_data", return_value="data"),
            patch("mrsiprep.reports.t1_correction.triplanar_slices", return_value={}),
            patch("mrsiprep.reports.t1_correction.render_triplanar_png"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _row(self, metabolite, **overrides):
        row = {
            "metabolite": metabolite,
            "t1_s": 1.38,
            "tr_s": 0.457,
            "flip_deg": 45.0,
            "field_strength_t": 3.0,
            "saturation_factor": 0.8123,
            "source": "literature",
            "status": "ok",
        }
        row.update(overrides)
        return row

    def test_table_formats_numeric_fields_with_expected_precision(self):
        rows = [self._row("CrPCr")]
        sections = build_t1_correction_qc_sections(self.config, "01", "01", {}, {}, rows)
        _heading, table_html = sections[0]
        self.assertIn("<td>1.380</td>", table_html)
        self.assertIn("<td>0.457</td>", table_html)
        self.assertIn("<td>45.0</td>", table_html)
        self.assertIn("<td>3.0</td>", table_html)
        self.assertIn("<td>0.8123</td>", table_html)

    def test_warnings_are_deduplicated_and_sorted(self):
        rows = [
            self._row("CrPCr", warnings="Low TR"),
            self._row("GluGln", warnings="Low TR"),  # duplicate, must collapse
            self._row("Ins", warnings="Atypical field strength"),
            self._row("GPCPCh", warnings=None),  # no warning, excluded
        ]
        sections = build_t1_correction_qc_sections(self.config, "01", "01", {}, {}, rows)
        _heading, table_html = sections[0]
        self.assertEqual(table_html.count("<strong>Warning:</strong>"), 2)
        atypical_idx = table_html.index("Atypical field strength")
        low_tr_idx = table_html.index("Low TR")
        self.assertLess(atypical_idx, low_tr_idx)  # sorted() -> "Atypical..." before "Low TR"

    def test_only_metabolites_present_in_both_preproc_and_corrected_get_a_section(self):
        preproc_maps = {"CrPCr": Path("a.nii.gz"), "GluGln": Path("b.nii.gz")}
        corrected_maps = {"CrPCr": Path("a2.nii.gz")}  # GluGln missing here
        sections = build_t1_correction_qc_sections(self.config, "01", "01", preproc_maps, corrected_maps, [])
        headings = [heading for heading, _ in sections]
        self.assertIn("Metabolite: CrPCr", headings)
        self.assertNotIn("Metabolite: GluGln", headings)

    def test_factor_note_present_when_matching_row_exists(self):
        preproc_maps = {"CrPCr": Path("a.nii.gz")}
        corrected_maps = {"CrPCr": Path("a2.nii.gz")}
        rows = [self._row("CrPCr", saturation_factor=0.7654)]
        sections = build_t1_correction_qc_sections(self.config, "01", "01", preproc_maps, corrected_maps, rows)
        _heading, body = sections[1]
        self.assertIn("Factor: 0.7654", body)

    def test_factor_note_absent_when_no_matching_row(self):
        preproc_maps = {"CrPCr": Path("a.nii.gz")}
        corrected_maps = {"CrPCr": Path("a2.nii.gz")}
        sections = build_t1_correction_qc_sections(self.config, "01", "01", preproc_maps, corrected_maps, [])
        _heading, body = sections[1]
        self.assertNotIn("Factor:", body)

    def test_colormap_cycles_through_the_palette_by_index(self):
        n = len(METABOLITE_COLORMAPS) + 1  # force wraparound to index 0
        metabolites = [f"MET{i}" for i in range(n)]
        preproc_maps = {met: Path(f"{met}.nii.gz") for met in metabolites}
        corrected_maps = dict(preproc_maps)
        with patch("mrsiprep.reports.t1_correction.render_triplanar_png") as render:
            build_t1_correction_qc_sections(self.config, "01", "01", preproc_maps, corrected_maps, [])
        first_call_cmap = render.call_args_list[0].kwargs["cmap"]
        wraparound_call_cmap = render.call_args_list[2 * len(METABOLITE_COLORMAPS)].kwargs["cmap"]
        self.assertEqual(first_call_cmap, wraparound_call_cmap)


if __name__ == "__main__":
    unittest.main()

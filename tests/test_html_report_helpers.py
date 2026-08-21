"""Tests for reports/html.py's smaller pure HTML-building helpers.

generate_subject_report()'s tab presence/gating is already covered by
test_html_report.py; these tests target the helper functions that file
mocks away (_sections_html, _outputs_html, _mrsinmrs_html,
_citations_html, _parcel_figures_html), which is why the file's overall
coverage was low despite that existing test.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.reports.html import (
    _citations_html,
    _mrsinmrs_html,
    _outputs_html,
    _parcel_figures_html,
    _sections_html,
)


class SectionsHtmlTests(unittest.TestCase):
    def test_none_renders_placeholder(self):
        self.assertIn("Not available", _sections_html(None))

    def test_empty_list_renders_placeholder(self):
        self.assertIn("Not available", _sections_html([]))

    def test_joins_heading_and_body_pairs(self):
        html = _sections_html([("Heading One", "<p>body one</p>"), ("Heading Two", "<p>body two</p>")])
        self.assertIn("<h3>Heading One</h3><p>body one</p>", html)
        self.assertIn("<h3>Heading Two</h3><p>body two</p>", html)


class OutputsHtmlTests(unittest.TestCase):
    def test_renders_sorted_key_value_list(self):
        html = _outputs_html({"zeta": "z_path", "alpha": "a_path"})
        alpha_idx = html.index("alpha")
        zeta_idx = html.index("zeta")
        self.assertLess(alpha_idx, zeta_idx)
        self.assertIn("<strong>alpha</strong>: <code>a_path</code>", html)

    def test_empty_dict_renders_empty_list(self):
        self.assertEqual(_outputs_html({}), "<ul></ul>")


class MrsinmrsHtmlTests(unittest.TestCase):
    def test_reports_value_error_from_malformed_json(self):
        config = SimpleNamespace(bids_dir=Path("/tmp/bids"))
        with patch("mrsiprep.reports.html.load_mrsinmrs", side_effect=ValueError("bad json")):
            html = _mrsinmrs_html(config, "01", "01")
        self.assertIn("Could not read mrsinmrs.json", html)
        self.assertIn("bad json", html)

    def test_no_sidecar_found_suggests_adding_one(self):
        config = SimpleNamespace(bids_dir=Path("/tmp/bids"))
        with patch("mrsiprep.reports.html.load_mrsinmrs", return_value={}), patch(
            "mrsiprep.reports.html.resolve_mrsinmrs", return_value={}
        ):
            html = _mrsinmrs_html(config, "01", "01")
        self.assertIn("No", html)
        self.assertIn("mrsinmrs.json", html)

    def test_resolved_params_render_with_units_and_skip_sequence_citation(self):
        config = SimpleNamespace(bids_dir=Path("/tmp/bids"))
        resolved = {"TE": "0.03", "MagneticFieldStrength": "3", "SequenceCitation": "should not appear"}
        with patch("mrsiprep.reports.html.load_mrsinmrs", return_value={"raw": True}), patch(
            "mrsiprep.reports.html.resolve_mrsinmrs", return_value=resolved
        ):
            html = _mrsinmrs_html(config, "01", "01")
        self.assertIn("<td>TE</td><td>0.03</td><td>s</td>", html)
        self.assertIn("<td>MagneticFieldStrength</td><td>3</td><td>T</td>", html)
        self.assertNotIn("SequenceCitation", html)
        self.assertNotIn("should not appear", html)


class CitationsHtmlTests(unittest.TestCase):
    def test_always_includes_mrsiprep_and_mrsinmrs_citations(self):
        config = SimpleNamespace()
        html = _citations_html(config)
        self.assertIn("CITATION.cff", html)
        self.assertIn("MRSinMRS", html)

    def test_no_preset_citation_omits_processing_parameters_line(self):
        config = SimpleNamespace()
        html = _citations_html(config)
        self.assertNotIn("Processing parameters replicate", html)

    def test_preset_citation_with_doi_builds_doi_link(self):
        config = SimpleNamespace(preset_citation={"label": "Some Study", "doi": "10.1000/xyz"})
        html = _citations_html(config)
        self.assertIn("https://doi.org/10.1000/xyz", html)
        self.assertIn("Some Study", html)

    def test_preset_citation_with_explicit_url_takes_priority(self):
        config = SimpleNamespace(preset_citation={"text": "Some Study", "url": "https://example.org/study", "doi": "10.1000/xyz"})
        html = _citations_html(config)
        self.assertIn("https://example.org/study", html)
        self.assertNotIn("doi.org", html)

    def test_preset_citation_without_url_or_doi_renders_plain_text(self):
        # The two other citation lines always contain their own <a href>
        # links, so this must check the "Processing parameters replicate"
        # line specifically, not the whole page's markup.
        config = SimpleNamespace(preset_citation={"label": "Some Study"})
        html = _citations_html(config)
        self.assertIn("Processing parameters replicate: Some Study</p>", html)
        self.assertNotIn("Processing parameters replicate: <a", html)


class ParcelFiguresHtmlTests(unittest.TestCase):
    def test_empty_when_no_figures_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(_parcel_figures_html(Path(tmpdir)), "")

    def test_includes_coverage_figure_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            figures_dir = Path(tmpdir) / "figures"
            figures_dir.mkdir()
            (figures_dir / "sub-01_desc-parcelcoverage.png").touch()
            html = _parcel_figures_html(Path(tmpdir))
        self.assertIn("anatomical coverage", html)
        self.assertIn("sub-01_desc-parcelcoverage.png", html)

    def test_includes_one_entry_per_crlb_metabolite_figure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            figures_dir = Path(tmpdir) / "figures"
            figures_dir.mkdir()
            (figures_dir / "sub-01_desc-parcelcrlbquality_met-CrPCr.png").touch()
            (figures_dir / "sub-01_desc-parcelcrlbquality_met-GluGln.png").touch()
            html = _parcel_figures_html(Path(tmpdir))
        self.assertIn("2 metabolites", html)
        self.assertIn("met-CrPCr", html)
        self.assertIn("met-GluGln", html)


if __name__ == "__main__":
    unittest.main()

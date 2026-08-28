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

from mrsiprep.reports.html import (
    _bids_project_name,
    _citations_html,
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
    def test_falls_back_to_a_flat_listing_without_a_root(self):
        html = _outputs_html({"qc": "/data/out/sub-01/confounds/qc.tsv"})
        self.assertIn("qc.tsv", html)
        self.assertIn("(qc)", html)

    def test_renders_a_tree_when_given_the_recording_directory(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ses-01"
            (root / "confounds").mkdir(parents=True)
            (root / "confounds" / "qc.tsv").write_text("x")
            (root / "reports").mkdir()
            (root / "reports" / "report.html").write_text("x")
            html = _outputs_html({}, root)
        self.assertIn("ses-01/", html)
        self.assertIn("confounds/", html)
        self.assertIn("qc.tsv", html)
        self.assertIn("\u2514\u2500\u2500", html)  # tree connectors
        # reports/ is the page the reader is already looking at.
        self.assertNotIn("report.html", html)


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

    def test_embeds_the_crlb_grid_full_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            figures = Path(tmp) / "figures"
            figures.mkdir()
            (figures / "sub-01_desc-parcelcrlbquality.png").write_bytes(b"x")
            html = _parcel_figures_html(Path(tmp))
        self.assertIn("Parcelwise CRLB quality", html)
        self.assertIn("sub-01_desc-parcelcrlbquality.png", html)
        # Not inside a flex row any more: 10 slices squeezed to a 240px column
        # are unreadable.
        self.assertNotIn("class='row'", html)

    def test_ignores_superseded_per_metabolite_figures(self):
        """A stale one-row-per-metabolite figure left in figures/ by an earlier
        run must not be embedded alongside the grid that replaced it."""
        with tempfile.TemporaryDirectory() as tmp:
            figures = Path(tmp) / "figures"
            figures.mkdir()
            (figures / "sub-01_desc-parcelcrlbquality.png").write_bytes(b"x")
            (figures / "sub-01_met-CrPCr_desc-parcelcrlbquality.png").write_bytes(b"x")
            (figures / "sub-01_met-Ins_desc-parcelcrlbquality.png").write_bytes(b"x")
            html = _parcel_figures_html(Path(tmp))
        self.assertEqual(html.count("<img"), 1)
        self.assertNotIn("met-CrPCr", html)


class BidsProjectNameTests(unittest.TestCase):
    """The report title must never fail to render over dataset metadata."""

    def _config(self, root):
        return SimpleNamespace(bids_dir=root)

    def test_uses_the_name_from_dataset_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "my-bids"
            root.mkdir()
            (root / "dataset_description.json").write_text('{"Name": "SynthMRSI-Project"}')
            self.assertEqual(_bids_project_name(self._config(root)), "SynthMRSI-Project")

    def test_falls_back_to_the_directory_name_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "my-bids"
            root.mkdir()
            self.assertEqual(_bids_project_name(self._config(root)), "my-bids")

    def test_malformed_json_falls_back_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "my-bids"
            root.mkdir()
            (root / "dataset_description.json").write_text("{not json")
            self.assertEqual(_bids_project_name(self._config(root)), "my-bids")

    def test_blank_or_missing_name_falls_back(self):
        for payload in ('{"Name": "   "}', '{"Name": null}', "{}"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "my-bids"
                root.mkdir()
                (root / "dataset_description.json").write_text(payload)
                self.assertEqual(_bids_project_name(self._config(root)), "my-bids", msg=payload)

    def test_non_string_name_is_coerced_rather_than_discarded(self):
        """A numeric Name is unusual but still a usable label; discarding it
        for the folder name would lose information the dataset did provide."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "my-bids"
            root.mkdir()
            (root / "dataset_description.json").write_text('{"Name": 42}')
            self.assertEqual(_bids_project_name(self._config(root)), "42")


if __name__ == "__main__":
    unittest.main()

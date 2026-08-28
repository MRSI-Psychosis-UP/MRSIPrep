"""Tests for reports/html.py's generate_subject_report -- the main
orchestration function that assembles the tabbed per-recording HTML
report. test_html_report_helpers.py already covers the smaller
_sections_html/_outputs_html/_mrsinmrs_html/_citations_html/
_parcel_figures_html helpers; this covers which TSVs get read, which
tabs get included, and the parcel_qc groupby/agg summary math.

build_preproc_overview_sections is mocked (it needs a fully-populated
run config unrelated to what's under test here); everything else
(leakage_table_html, coverage_report_html, the _*_html helpers) runs
for real.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.reports.html import generate_subject_report


class GenerateSubjectReportFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.config = SimpleNamespace(
            derivative_dir=self.tmp / "derivatives",
            bids_dir=self.tmp / "bids",  # no mrsinmrs.json here -> the "not found" branch
            parcellation_mode="chimera",
            tissue_backend="synthseg-fast",
        )
        patcher = patch(
            "mrsiprep.reports.html.build_preproc_overview_sections",
            return_value=[("Preproc heading", "<p>preproc body</p>")],
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmpdir.cleanup()


class GenerateSubjectReportMinimalTests(GenerateSubjectReportFixture):
    def test_writes_report_with_core_tabs_and_no_optional_tabs(self):
        out = generate_subject_report(self.config, "01", "01", outputs={})
        self.assertTrue(out.exists())
        html = out.read_text()
        self.assertIn("sub-01 ses-01</h1>", html)
        self.assertIn("MRSIPrep report:", html)
        self.assertIn("No QC table available.", html)
        self.assertIn("preproc body", html)
        self.assertNotIn("id='t1-correction'", html)
        self.assertNotIn("id='connectivity'", html)
        self.assertIn("id='runtime'", html)
        self.assertIn("id='outputs'", html)
        self.assertIn("found at the BIDS root", html)

    def test_no_session_omits_ses_suffix(self):
        out = generate_subject_report(self.config, "01", None, outputs={})
        html = out.read_text()
        # The BIDS project name now prefixes both, so assert on the
        # subject/session part and on the absence of a ses- suffix.
        self.assertIn("sub-01</title>", html)
        self.assertIn("sub-01</h1>", html)
        self.assertNotIn("ses-", html.split("</h1>")[0])

    def test_mrsi_raw_sections_appended_after_qc_table(self):
        out = generate_subject_report(
            self.config, "01", "01", outputs={}, qc_sections={"mrsi_raw": [("Raw heading", "<p>raw body</p>")]}
        )
        html = out.read_text()
        self.assertIn("Raw metabolite maps (pre-pipeline)", html)
        self.assertIn("raw body", html)


class GenerateSubjectReportQcSummaryTests(GenerateSubjectReportFixture):
    def test_qc_summary_table_is_rendered_when_present(self):
        qc_path = self.tmp / "qc_summary.tsv"
        qc_path.write_text("metric\tvalue\nsnr\t12.5\n")
        out = generate_subject_report(self.config, "01", "01", outputs={"qc_summary": qc_path})
        html = out.read_text()
        self.assertNotIn("No QC table available.", html)
        self.assertIn("snr", html)
        self.assertIn("12.5", html)

    def test_missing_qc_summary_path_falls_back_to_placeholder(self):
        out = generate_subject_report(self.config, "01", "01", outputs={"qc_summary": self.tmp / "nope.tsv"})
        self.assertIn("No QC table available.", out.read_text())


class GenerateSubjectReportRegionalTableTests(GenerateSubjectReportFixture):
    def test_regional_table_is_read_without_error_when_present(self):
        """NOTE: generate_subject_report reads and renders outputs["regional_table"]
        into regional_html (lines 59-62 of html.py) but that variable is never
        referenced again -- it doesn't appear in any tab. This looks like an
        unintentional omission (dead computation), not a documented design
        choice, so this test only confirms the read path doesn't error rather
        than asserting on report content that doesn't actually exist."""
        regional_path = self.tmp / "regional.tsv"
        regional_path.write_text("parcel\tvalue\nFrontal\t1.23\n")
        out = generate_subject_report(self.config, "01", "01", outputs={"regional_table": regional_path})
        self.assertTrue(out.exists())

    def test_missing_regional_table_path_is_also_a_silent_no_op(self):
        out = generate_subject_report(self.config, "01", "01", outputs={"regional_table": self.tmp / "nope.tsv"})
        self.assertTrue(out.exists())


class GenerateSubjectReportParcelQcTests(GenerateSubjectReportFixture):
    def test_coverage_tab_explains_qc_valid_fraction_instead_of_summarising_coverage(self):
        """anatomical_coverage_percent's mean is computed over the grouped
        (one-row-per-parcel) overview, while mean_crlb's mean is computed
        over the raw, ungrouped parcel_df -- two different populations when
        a parcel has multiple rows (e.g. one per metabolite)."""
        parcel_qc_path = self.tmp / "parcel_qc.tsv"
        parcel_qc_path.write_text(
            "parcel_id\tparcel_name\themisphere\tanatomical_coverage_percent\tmean_crlb\tqc_valid_fraction\n"
            "1\tFrontal\tL\t80.0\t10.0\t0.9\n"
            "1\tFrontal\tL\t80.0\t20.0\t0.8\n"
            "2\tOccipital\tR\t60.0\t30.0\t0.7\n"
        )
        out = generate_subject_report(self.config, "01", "01", outputs={"parcel_qc": parcel_qc_path})
        html = out.read_text()
        # The coverage summary sentence was dropped; the tab now explains what
        # qc_valid_fraction means instead, and ranks by it.
        self.assertIn("qc_valid_fraction", html)
        self.assertNotIn("Mean anatomical MRSI coverage", html)
        self.assertNotIn("anatomical_coverage_percent", html)
        # Worst-first ordering: the 0.700 parcel precedes the 0.850 one.
        self.assertLess(html.index("Occipital"), html.index("Frontal"))
        self.assertIn("Frontal", html)
        self.assertIn("Occipital", html)
        self.assertNotIn("No parcelwise QC table available.", html)

    def test_missing_parcel_qc_falls_back_to_placeholder(self):
        out = generate_subject_report(self.config, "01", "01", outputs={"parcel_qc": self.tmp / "nope.tsv"})
        self.assertIn("No parcelwise QC table available.", out.read_text())


class GenerateSubjectReportLeakageQcTests(GenerateSubjectReportFixture):
    def test_leakage_table_rendered_for_matching_space(self):
        leakage_path = self.tmp / "leakage.tsv"
        leakage_path.write_text("space\tmetabolite\tleakage\nT1w\tCrPCr\t0.05\n")
        out = generate_subject_report(self.config, "01", "01", outputs={"leakage_qc": leakage_path})
        html = out.read_text()
        self.assertIn("Signal-weighted leakage", html)
        self.assertIn("0.050", html)


class GenerateSubjectReportConditionalTabsTests(GenerateSubjectReportFixture):
    def test_t1_correction_tab_appears_only_when_section_key_present(self):
        without = generate_subject_report(self.config, "01", "01", outputs={}, qc_sections={})
        self.assertNotIn("id='t1-correction'", without.read_text())

        with_section = generate_subject_report(
            self.config, "01", "01", outputs={}, qc_sections={"t1_correction": [("T1 corr", "<p>body</p>")]}
        )
        self.assertIn("id='t1-correction'", with_section.read_text())

    def test_t1_correction_tab_appears_even_for_an_empty_but_present_section_list(self):
        """The guard is `is not None`, not truthiness -- an empty list still
        adds the tab (with a placeholder body), unlike an absent key, which
        omits the tab entirely."""
        out = generate_subject_report(self.config, "01", "01", outputs={}, qc_sections={"t1_correction": []})
        self.assertIn("id='t1-correction'", out.read_text())

    def test_connectivity_tab_appears_only_when_section_key_present(self):
        without = generate_subject_report(self.config, "01", "01", outputs={}, qc_sections={})
        self.assertNotIn("id='connectivity'", without.read_text())

        with_section = generate_subject_report(
            self.config, "01", "01", outputs={}, qc_sections={"connectivity": [("Conn", "<p>body</p>")]}
        )
        self.assertIn("id='connectivity'", with_section.read_text())


if __name__ == "__main__":
    unittest.main()

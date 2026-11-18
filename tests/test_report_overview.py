import tempfile
import unittest
from pathlib import Path

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.reports.overview import (
    _STATUS_FAILED,
    _STATUS_NO_DATA,
    _STATUS_SUCCESS,
    _STATUS_UNPROCESSED,
    _log_indicates_failure,
    _median_dice,
    _recording_row,
    update_report_overview,
)


def _make_config(bids_dir: Path, derivative_dir: Path) -> MRSIPrepConfig:
    return MRSIPrepConfig(
        bids_dir,
        derivative_dir.parent,
        "participant",
        metabolites=["CrPCr"],
        ref_met="CrPCr",
    )


def _touch_raw_mrsi(bids_dir: Path, subject: str, session: str) -> None:
    (bids_dir / f"sub-{subject}" / f"ses-{session}").mkdir(parents=True, exist_ok=True)
    path = bids_dir / "derivatives" / "mrsi-orig" / f"sub-{subject}" / f"ses-{session}" / f"sub-{subject}_ses-{session}_space-orig_met-CrPCr_desc-signal_mrsi.nii.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


class LogIndicatesFailureTests(unittest.TestCase):
    def test_missing_log_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(_log_indicates_failure(Path(tmp) / "missing.txt"))

    def test_clean_log_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.txt"
            log.write_text("everything ran fine")
            self.assertFalse(_log_indicates_failure(log))

    def test_traceback_in_log_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.txt"
            log.write_text("Traceback (most recent call last):\n  oops")
            self.assertTrue(_log_indicates_failure(log))


class MedianDiceTests(unittest.TestCase):
    def test_missing_tsv_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(Path(tmp) / "bids", Path(tmp) / "derivatives" / "mrsiprep")
            self.assertIsNone(_median_dice(config, "01", "01"))

    def test_reads_median_row_from_tsv(self):
        with tempfile.TemporaryDirectory() as tmp:
            derivative_dir = Path(tmp) / "derivatives" / "mrsiprep"
            config = _make_config(Path(tmp) / "bids", derivative_dir)
            tsv = derivative_dir / "sub-01" / "ses-01" / "confounds" / "sub-01_ses-01_desc-ventricleqc.tsv"
            tsv.parent.mkdir(parents=True, exist_ok=True)
            tsv.write_text("metabolite\tdice\tn_detected\tn_reference\nCrPCr\t0.5\t10\t12\nmedian\t0.5\t\t\n")
            self.assertEqual(_median_dice(config, "01", "01"), 0.5)


class RecordingRowStatusTests(unittest.TestCase):
    def test_no_raw_data_is_no_data_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            bids_dir = Path(tmp) / "bids"
            derivative_dir = bids_dir / "derivatives" / "mrsiprep"
            config = _make_config(bids_dir, derivative_dir)
            from mrsiprep.io.bids import BIDSLayout

            layout = BIDSLayout.from_config(config)
            row = _recording_row(config, layout, "01", "01")
            self.assertEqual(row["status"], _STATUS_NO_DATA)
            self.assertIsNone(row["report"])
            self.assertIsNone(row["median_dice"])

    def test_raw_data_with_no_report_and_no_log_is_unprocessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bids_dir = Path(tmp) / "bids"
            derivative_dir = bids_dir / "derivatives" / "mrsiprep"
            _touch_raw_mrsi(bids_dir, "01", "01")
            config = _make_config(bids_dir, derivative_dir)
            from mrsiprep.io.bids import BIDSLayout

            layout = BIDSLayout.from_config(config)
            row = _recording_row(config, layout, "01", "01")
            self.assertEqual(row["status"], _STATUS_UNPROCESSED)

    def test_raw_data_with_report_and_provenance_is_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            bids_dir = Path(tmp) / "bids"
            derivative_dir = bids_dir / "derivatives" / "mrsiprep"
            _touch_raw_mrsi(bids_dir, "01", "01")
            config = _make_config(bids_dir, derivative_dir)
            reports_dir = derivative_dir / "sub-01" / "ses-01" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            (reports_dir / "sub-01_ses-01_desc-report.html").write_text("<html></html>")
            (reports_dir / "sub-01_ses-01_desc-provenance.json").write_text("{}")
            from mrsiprep.io.bids import BIDSLayout

            layout = BIDSLayout.from_config(config)
            row = _recording_row(config, layout, "01", "01")
            self.assertEqual(row["status"], _STATUS_SUCCESS)
            self.assertIsNotNone(row["report"])

    def test_raw_data_with_crash_log_and_no_report_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bids_dir = Path(tmp) / "bids"
            derivative_dir = bids_dir / "derivatives" / "mrsiprep"
            _touch_raw_mrsi(bids_dir, "01", "01")
            config = _make_config(bids_dir, derivative_dir)
            logs_dir = derivative_dir / "sub-01" / "ses-01" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "sub-01_ses-01_desc-mrsiprep_log.txt").write_text("Traceback (most recent call last):\n  boom")
            from mrsiprep.io.bids import BIDSLayout

            layout = BIDSLayout.from_config(config)
            row = _recording_row(config, layout, "01", "01")
            self.assertEqual(row["status"], _STATUS_FAILED)


class UpdateReportOverviewTests(unittest.TestCase):
    def test_writes_html_with_one_row_per_recording_and_legend(self):
        with tempfile.TemporaryDirectory() as tmp:
            bids_dir = Path(tmp) / "bids"
            derivative_dir = bids_dir / "derivatives" / "mrsiprep"
            _touch_raw_mrsi(bids_dir, "01", "01")
            (bids_dir / "sub-02" / "ses-01").mkdir(parents=True, exist_ok=True)
            config = _make_config(bids_dir, derivative_dir)

            out = update_report_overview(config)

            self.assertTrue(out.is_file())
            self.assertEqual(out, derivative_dir / "report_overview.html")
            html = out.read_text(encoding="utf-8")
            self.assertIn("sub-01_ses-01", html)
            self.assertIn("sub-02_ses-01", html)
            self.assertIn("class='legend'", html)


if __name__ == "__main__":
    unittest.main()

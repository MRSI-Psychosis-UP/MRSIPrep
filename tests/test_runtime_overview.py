import types
import unittest

from mrsiprep.reports.runtime_overview import _format_seconds, build_runtime_qc_sections


class FormatSecondsTests(unittest.TestCase):
    def test_sub_minute(self):
        self.assertEqual(_format_seconds(12.3), "12.3s")

    def test_minutes(self):
        self.assertEqual(_format_seconds(75.4), "1m 15.4s")

    def test_hours(self):
        self.assertEqual(_format_seconds(3661.0), "1h 1m 01.0s")


class BuildRuntimeQcSectionsTests(unittest.TestCase):
    def test_empty_timings_reports_no_data(self):
        config = types.SimpleNamespace(nproc=1, nthreads=4)
        sections = build_runtime_qc_sections(config, [])
        self.assertIn("No timing data recorded", sections[0][1])

    def test_includes_per_step_table_and_context(self):
        config = types.SimpleNamespace(nproc=2, nthreads=8)
        timings = [
            {"step": "Tissue segmentation", "seconds": 30.0},
            {"step": "Registration", "seconds": 70.0},
        ]
        sections = build_runtime_qc_sections(config, timings)
        heading, body = sections[0]
        self.assertIn("Tissue segmentation", body)
        self.assertIn("Registration", body)
        self.assertIn("nproc", body)
        self.assertIn("2", body)
        self.assertIn("8", body)
        # 30s of 100s total = 30.0%
        self.assertIn("30.0%", body)
        self.assertIn("70.0%", body)

    def test_total_row_sums_step_durations(self):
        config = types.SimpleNamespace(nproc=1, nthreads=1)
        timings = [{"step": "A", "seconds": 10.0}, {"step": "B", "seconds": 20.0}]
        sections = build_runtime_qc_sections(config, timings)
        body = sections[0][1]
        self.assertIn("30.0s", body)  # total = 10 + 20


if __name__ == "__main__":
    unittest.main()

import re
import unittest
from types import SimpleNamespace

from mrsiprep.reports.runtime_overview import (
    _format_seconds,
    build_runtime_qc_sections,
)


class FormatSecondsTests(unittest.TestCase):
    def test_sub_minute_renders_as_seconds_with_one_decimal(self):
        self.assertEqual(_format_seconds(0.0), "0.0s")
        self.assertEqual(_format_seconds(12.34), "12.3s")
        self.assertEqual(_format_seconds(59.94), "59.9s")

    def test_exactly_one_minute_crosses_into_minute_form(self):
        self.assertEqual(_format_seconds(60), "1m 00.0s")

    def test_minutes_pad_seconds_to_two_digits(self):
        # 04.1f keeps single-digit seconds aligned ("5.0s" -> "05.0s"),
        # which is what makes the table column line up.
        self.assertEqual(_format_seconds(65.0), "1m 05.0s")
        self.assertEqual(_format_seconds(125.5), "2m 05.5s")

    def test_exactly_one_hour_crosses_into_hour_form(self):
        self.assertEqual(_format_seconds(3600), "1h 0m 00.0s")

    def test_hours_carry_remaining_minutes_and_seconds(self):
        self.assertEqual(_format_seconds(3600 + 2 * 60 + 3.5), "1h 2m 03.5s")

    def test_multi_hour_duration_does_not_wrap_hours(self):
        self.assertEqual(_format_seconds(5 * 3600 + 59 * 60 + 59.9), "5h 59m 59.9s")


class BuildRuntimeQcSectionsTests(unittest.TestCase):
    def _config(self, **overrides):
        base = dict(nproc=4, nthreads=8)
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_empty_timings_returns_single_placeholder_section(self):
        sections = build_runtime_qc_sections(self._config(), [])
        self.assertEqual(len(sections), 1)
        heading, body = sections[0]
        self.assertEqual(heading, "Runtime")
        self.assertIn("No timing data recorded", body)

    def test_returns_one_section_headed_per_step_duration(self):
        sections = build_runtime_qc_sections(self._config(), [{"step": "A", "seconds": 1.0}])
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0][0], "Per-step duration")

    def test_every_step_gets_its_own_row_in_order(self):
        timings = [
            {"step": "Tissue segmentation", "seconds": 10.0},
            {"step": "Registration", "seconds": 30.0},
        ]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        self.assertLess(body.index("Tissue segmentation"), body.index("Registration"))
        for entry in timings:
            self.assertIn(entry["step"], body)

    def test_percentages_are_share_of_total_and_sum_to_100(self):
        timings = [
            {"step": "A", "seconds": 25.0},
            {"step": "B", "seconds": 75.0},
        ]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        self.assertIn("25.0%", body)
        self.assertIn("75.0%", body)

    def test_total_row_sums_every_step(self):
        timings = [
            {"step": "A", "seconds": 30.0},
            {"step": "B", "seconds": 45.0},
        ]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        # 75s total -> "1m 15.0s", and the total row is always 100.0%.
        self.assertIn("1m 15.0s", body)
        self.assertIn("Total (through report generation)", body)
        self.assertIn("100.0%", body)

    def test_single_step_is_100_percent_of_itself(self):
        _, body = build_runtime_qc_sections(self._config(), [{"step": "Only", "seconds": 3.0}])[0]
        # One data row at 100.0% plus the total row at 100.0%.
        self.assertEqual(body.count("100.0%"), 2)

    def test_nproc_and_nthreads_context_is_rendered(self):
        _, body = build_runtime_qc_sections(self._config(nproc=2, nthreads=16), [{"step": "A", "seconds": 1.0}])[0]
        self.assertIn("<code>2</code>", body)
        self.assertIn("<code>16</code>", body)

    def test_missing_nproc_nthreads_fall_back_to_na_rather_than_raising(self):
        _, body = build_runtime_qc_sections(SimpleNamespace(), [{"step": "A", "seconds": 1.0}])[0]
        self.assertEqual(body.count("<code>n/a</code>"), 2)

    def test_note_explains_what_the_total_excludes(self):
        _, body = build_runtime_qc_sections(self._config(), [{"step": "A", "seconds": 1.0}])[0]
        self.assertIn("report-generation step's own duration", body)
        self.assertIn("--nproc", body)

    def test_table_is_well_formed_with_one_row_per_step_plus_header_and_total(self):
        timings = [{"step": f"S{i}", "seconds": float(i + 1)} for i in range(4)]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        self.assertEqual(body.count("<tr>"), len(timings) + 2)  # + header + total
        self.assertEqual(body.count("<table>"), 1)
        self.assertEqual(body.count("</table>"), 1)

    def test_zero_duration_steps_do_not_divide_by_zero_when_total_is_positive(self):
        timings = [
            {"step": "Instant", "seconds": 0.0},
            {"step": "Slow", "seconds": 10.0},
        ]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        self.assertIn("0.0%", body)
        self.assertIn("<td>0.0s</td>", body)

    def test_percent_cells_always_carry_one_decimal(self):
        timings = [{"step": "A", "seconds": 1.0}, {"step": "B", "seconds": 2.0}]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        for percent in re.findall(r">(\d+\.\d)%<", body):
            self.assertRegex(percent, r"^\d+\.\d$")


if __name__ == "__main__":
    unittest.main()

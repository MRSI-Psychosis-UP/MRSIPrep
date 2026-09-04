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
        # Everything enabled, so pipeline_trace adds no "not applied" rows and
        # these tests measure only the timed-step rendering. A config missing
        # these fields is a programming error the report now surfaces, so the
        # fixture has to be realistic rather than minimal.
        base = dict(
            nproc=4, nthreads=8, parcellation_mode="atlas", no_pvc=False,
            t1_correction="literature", write_connectivity=True,
            output_spaces=["MNI152NLin2009cAsym"], transform="mni",
        )
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


class StepOutcomeTests(unittest.TestCase):
    """Duration alone does not say whether a step worked, and a step that was
    gated out is absent entirely -- which reads the same as 'ran instantly'."""

    def _config(self, **overrides):
        base = dict(
            nproc=1, nthreads=8, parcellation_mode="synthseg", no_pvc=True,
            t1_correction="none", write_connectivity=False,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_processed_and_failed_steps_are_labelled(self):
        timings = [
            {"step": "Tissue segmentation", "seconds": 10.0, "outcome": "processed"},
            {"step": "Reports", "seconds": 2.0, "outcome": "failed"},
        ]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        self.assertIn("PROC", body)
        self.assertIn("FAILED", body)

    def test_outcome_defaults_to_processed_for_older_timing_entries(self):
        # Entries recorded before the outcome field existed must still render.
        _, body = build_runtime_qc_sections(self._config(), [{"step": "X", "seconds": 1.0}])[0]
        self.assertIn("PROC", body)

    def test_config_gated_steps_read_as_not_applied_not_skipped(self):
        """'Skipped' conflates two unrelated things. A step the config never
        asked for is N/A; a step whose outputs already existed is REUSED."""
        timings = [{"step": "Tissue segmentation", "seconds": 10.0, "outcome": "processed"}]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        self.assertIn("N/A", body)
        self.assertNotIn("SKIPPED", body)
        self.assertIn("Partial volume correction", body)
        self.assertIn("--no-pvc", body)

    def test_reused_outputs_are_distinguished_from_freshly_computed(self):
        timings = [
            {"step": "Tissue segmentation", "seconds": 40.0, "outcome": "processed"},
            {"step": "MRSI-T1w-MNI registration", "seconds": 0.2, "outcome": "cached"},
        ]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        self.assertIn("REUSED", body)
        self.assertIn("PROC", body)

    def test_legend_explains_how_to_force_recomputation(self):
        _, body = build_runtime_qc_sections(self._config(), [{"step": "X", "seconds": 1.0}])[0]
        self.assertIn("--overwrite", body)

    def test_a_step_that_ran_is_not_also_listed_as_skipped(self):
        """PVC ran here, so it must appear once with its duration, not twice."""
        timings = [{"step": "Partial volume correction", "seconds": 5.0, "outcome": "processed"}]
        _, body = build_runtime_qc_sections(self._config(no_pvc=False), timings)[0]
        self.assertEqual(body.count("Partial volume correction"), 1)
        table = body[body.index("<table>"):]
        self.assertNotIn("N/A", table.split("Partial volume correction")[1][:80])

    def test_skipped_rows_carry_no_duration_or_share(self):
        timings = [{"step": "Tissue segmentation", "seconds": 10.0, "outcome": "processed"}]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        # Scope to the table: the legend also mentions N/A.
        table = body[body.index("<table>"):]
        skipped_row = [row for row in table.split("<tr>") if "N/A" in row][0]
        self.assertIn("<td>-</td>", skipped_row)

    def test_percentages_still_sum_over_timed_steps_only(self):
        timings = [
            {"step": "A", "seconds": 30.0, "outcome": "processed"},
            {"step": "B", "seconds": 10.0, "outcome": "processed"},
        ]
        _, body = build_runtime_qc_sections(self._config(), timings)[0]
        self.assertIn("75.0%", body)
        self.assertIn("25.0%", body)


if __name__ == "__main__":
    unittest.main()

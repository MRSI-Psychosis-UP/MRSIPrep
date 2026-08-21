import unittest
from types import SimpleNamespace

from mrsiprep.workflows.participant import (
    _build_preflight_table,
    _preflight_missing_items,
    _preflight_row_cells,
    _preflight_tissue_label,
    _preflight_transform_columns,
    _report_cpu_budget,
    _report_preflight_summary,
)


def _row(**overrides) -> dict:
    row = {
        "recording_id": "sub-S001_ses-V1",
        "subject": "S001",
        "session": "V1",
        "t1": True,
        "mrsi_found": 5,
        "mrsi_expected": 5,
        "crlb_found": 5,
        "snr": True,
        "fwhm": True,
        "brainmask": True,
        "tissue": "[cyan]AUTO[/cyan]",
        "transforms": {"mrsi": True, "anat": True},
        "freesurfer": None,
        "corrupt_items": [],
    }
    row.update(overrides)
    return row


class PreflightTransformColumnsTests(unittest.TestCase):
    def test_non_longitudinal_has_two_stages(self):
        config = SimpleNamespace(longitudinal=False)
        self.assertEqual(_preflight_transform_columns(config), [("mrsi", "MRSI→T1"), ("anat", "T1→MNI")])

    def test_longitudinal_adds_template_stage(self):
        config = SimpleNamespace(longitudinal=True)
        columns = _preflight_transform_columns(config)
        self.assertEqual(columns[-1], ("t1-template", "Ses→Template"))
        self.assertEqual(len(columns), 3)


class PreflightTissueLabelTests(unittest.TestCase):
    def test_auto_backend_shows_auto_marker(self):
        config = SimpleNamespace(tissue_backend="synthseg-fast")
        label = _preflight_tissue_label(layout=None, subject="S001", session="V1", config=config)
        self.assertEqual(label, "[cyan]AUTO[/cyan]")

    def test_existing_backend_reports_per_probseg_status(self):
        config = SimpleNamespace(tissue_backend="existing")
        layout = SimpleNamespace(cat12_probseg=lambda subject, session, idx: idx != 2)
        label = _preflight_tissue_label(layout, "S001", "V1", config)
        self.assertEqual(label, "[green]p1[/green] [red]p2[/red] [green]p3[/green]")


class PreflightRowCellsTests(unittest.TestCase):
    def test_complete_row_uses_check_marks(self):
        row = _row()
        cells = _preflight_row_cells(row, _preflight_transform_columns(SimpleNamespace(longitudinal=False)), show_integrity=False, show_freesurfer=False)
        self.assertEqual(cells[0], "sub-S001_ses-V1")
        self.assertIn("[green]✔[/green]", cells)
        self.assertNotIn("[red]X[/red]", cells)

    def test_missing_t1_shows_cross_mark(self):
        row = _row(t1=False)
        cells = _preflight_row_cells(row, [], show_integrity=False, show_freesurfer=False)
        self.assertEqual(cells[1], "[red]X[/red]")

    def test_partial_mrsi_count_is_red(self):
        row = _row(mrsi_found=3, mrsi_expected=5)
        cells = _preflight_row_cells(row, [], show_integrity=False, show_freesurfer=False)
        self.assertEqual(cells[2], "[red]3/5[/red]")

    def test_integrity_column_lists_corrupt_items(self):
        row = _row(corrupt_items=["T1w", "MRSI-CrPCr"])
        cells = _preflight_row_cells(row, [], show_integrity=True, show_freesurfer=False)
        self.assertEqual(cells[-1], "[red]CORRUPT (T1w, MRSI-CrPCr)[/red]")

    def test_integrity_column_check_mark_when_clean(self):
        row = _row(corrupt_items=[])
        cells = _preflight_row_cells(row, [], show_integrity=True, show_freesurfer=False)
        self.assertEqual(cells[-1], "[green]✔[/green]")

    def test_freesurfer_column_na_when_not_applicable(self):
        row = _row(freesurfer=None)
        cells = _preflight_row_cells(row, [], show_integrity=False, show_freesurfer=True)
        self.assertEqual(cells[-1], "[grey58]N/A[/grey58]")

    def test_freesurfer_column_proc_when_incomplete(self):
        row = _row(freesurfer=False)
        cells = _preflight_row_cells(row, [], show_integrity=False, show_freesurfer=True)
        self.assertEqual(cells[-1], "[orange3]PROC[/orange3]")

    def test_transform_columns_appended_in_order(self):
        row = _row(transforms={"mrsi": True, "anat": False})
        columns = [("mrsi", "MRSI→T1"), ("anat", "T1→MNI")]
        cells = _preflight_row_cells(row, columns, show_integrity=False, show_freesurfer=False)
        self.assertEqual(cells[-2:], ["[green]✔[/green]", "[orange3]PROC[/orange3]"])


class PreflightMissingItemsTests(unittest.TestCase):
    def _config(self, **overrides):
        base = dict(quality_metrics=["snr", "linewidth", "crlb"], tissue_backend="synthseg-fast")
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_complete_row_has_no_missing_items(self):
        self.assertEqual(_preflight_missing_items(_row(), self._config()), [])

    def test_missing_t1_flagged(self):
        self.assertIn("T1w", _preflight_missing_items(_row(t1=False), self._config()))

    def test_partial_mrsi_flagged_with_counts(self):
        items = _preflight_missing_items(_row(mrsi_found=2, mrsi_expected=5), self._config())
        self.assertIn("MRSI 2/5", items)

    def test_crlb_only_flagged_when_quality_metric_enabled(self):
        row = _row(crlb_found=1, mrsi_expected=5)
        self.assertIn("CRLB 1/5", _preflight_missing_items(row, self._config(quality_metrics=["crlb"])))
        self.assertNotIn("CRLB 1/5", _preflight_missing_items(row, self._config(quality_metrics=["snr"])))

    def test_tissue_flagged_for_any_existing_backend_with_red_marker(self):
        # No longer depends on parcellation_mode -- flagged for any config
        # using --tissue-backend existing.
        row = _row(tissue="[red]p2[/red]")
        config = self._config(tissue_backend="existing")
        self.assertIn("Tissue", _preflight_missing_items(row, config))

        config_synthseg_fast = self._config(tissue_backend="synthseg-fast")
        self.assertNotIn("Tissue", _preflight_missing_items(row, config_synthseg_fast))

    def test_corrupt_items_flagged(self):
        row = _row(corrupt_items=["SNR"])
        items = _preflight_missing_items(row, self._config())
        self.assertIn("CORRUPT (SNR)", items)


class BuildPreflightTableTests(unittest.TestCase):
    def test_optional_columns_included_only_when_requested(self):
        config = SimpleNamespace(longitudinal=False)
        columns = _preflight_transform_columns(config)

        minimal = _build_preflight_table(config, columns, show_integrity=False, show_freesurfer=False)
        with_extras = _build_preflight_table(config, columns, show_integrity=True, show_freesurfer=True)

        self.assertEqual(len(with_extras.columns), len(minimal.columns) + 2)


class ReportPreflightSummaryTests(unittest.TestCase):
    def test_success_message_when_nothing_missing(self):
        messages = []
        debug = SimpleNamespace(error=lambda msg: messages.append(("error", msg)), success=lambda msg: messages.append(("success", msg)))
        _report_preflight_summary(debug, summaries=[_row()], missing_recordings=[], total_missing_files=0)
        self.assertEqual(messages, [("success", "All required inputs are available for the selected recordings.")])

    def test_error_message_lists_affected_recordings(self):
        messages = []
        debug = SimpleNamespace(error=lambda msg: messages.append(("error", msg)), success=lambda msg: messages.append(("success", msg)))
        _report_preflight_summary(
            debug,
            summaries=[_row(), _row(recording_id="sub-S002")],
            missing_recordings=["sub-S002"],
            total_missing_files=2,
        )
        self.assertEqual(len(messages), 1)
        kind, msg = messages[0]
        self.assertEqual(kind, "error")
        self.assertIn("1/2 recordings", msg)
        self.assertIn("sub-S002", msg)


class ReportCpuBudgetTests(unittest.TestCase):
    def test_no_warning_reports_cpu_budget_line(self):
        messages = []
        debug = SimpleNamespace(always=lambda msg: messages.append(msg))
        config = SimpleNamespace(resolve_cpu_budget=lambda: (2, 4, None))
        _report_cpu_budget(debug, config)
        self.assertEqual(len(messages), 1)
        self.assertIn("CPU budget: --nproc 2 x --nthreads 4 = 8 threads", messages[0])

    def test_warning_is_reported_instead_of_budget_line(self):
        messages = []
        debug = SimpleNamespace(always=lambda msg: messages.append(msg))
        config = SimpleNamespace(resolve_cpu_budget=lambda: (8, 8, "coercing --nthreads"))
        _report_cpu_budget(debug, config)
        self.assertEqual(len(messages), 1)
        self.assertIn("coercing --nthreads", messages[0])
        self.assertNotIn("CPU budget", messages[0])


if __name__ == "__main__":
    unittest.main()

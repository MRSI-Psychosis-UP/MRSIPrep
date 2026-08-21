import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mrsiprep.cli.parser import parse_args as _parse_args
from mrsiprep.io.bids import Recording
from mrsiprep.workflows import participant as P

_REQUIRED_ARGS = ["--metabolites", "CrPCr", "--ref-met", "CrPCr"]


def make_config(argv, **overrides):
    cfg = _parse_args(argv + _REQUIRED_ARGS)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


class PreflightT1StatusTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.t1_path = Path(self._tmpdir.name) / "sub-01_T1w.nii.gz"
        self.t1_path.touch()
        self.addCleanup(self._tmpdir.cleanup)

    def test_reports_present_and_valid(self):
        layout = MagicMock()
        layout.t1.return_value = self.t1_path
        config = SimpleNamespace(t1_pattern="desc-brain_T1w")
        with patch("mrsiprep.utils.images.nifti_validity_error", return_value=None):
            status, corrupt = P._preflight_t1_status(layout, "01", "01", config, check_integrity=True)
        self.assertTrue(status)
        self.assertFalse(corrupt)

    def test_reports_missing_when_layout_returns_none(self):
        layout = MagicMock()
        layout.t1.return_value = None
        config = SimpleNamespace(t1_pattern="desc-brain_T1w")
        status, corrupt = P._preflight_t1_status(layout, "01", "01", config, check_integrity=True)
        self.assertFalse(status)
        self.assertFalse(corrupt)

    def test_corrupt_flag_false_when_integrity_check_disabled(self):
        layout = MagicMock()
        layout.t1.return_value = self.t1_path
        config = SimpleNamespace(t1_pattern="desc-brain_T1w")
        with patch("mrsiprep.utils.images.nifti_validity_error", return_value="bad header"):
            status, corrupt = P._preflight_t1_status(layout, "01", "01", config, check_integrity=False)
        self.assertTrue(status)
        self.assertFalse(corrupt)


class PreflightCorruptItemsTests(unittest.TestCase):
    def test_returns_empty_when_integrity_check_disabled(self):
        inputs = SimpleNamespace(metabolite_maps={}, crlb_maps={}, snr_map=None, linewidth_map=None)
        self.assertEqual(P._preflight_corrupt_items(inputs, t1_corrupt=True, check_integrity=False), [])

    def test_names_each_corrupt_category(self):
        inputs = SimpleNamespace(
            metabolite_maps={"CrPCr": Path("/tmp/crpcr.nii.gz")},
            crlb_maps={"CrPCr": Path("/tmp/crlb.nii.gz")},
            snr_map=Path("/tmp/snr.nii.gz"),
            linewidth_map=Path("/tmp/fwhm.nii.gz"),
        )
        with patch("mrsiprep.utils.images.nifti_validity_error", return_value="corrupt"):
            items = P._preflight_corrupt_items(inputs, t1_corrupt=True, check_integrity=True)
        self.assertEqual(set(items), {"T1w", "MRSI-CrPCr", "CRLB-CrPCr", "SNR", "FWHM"})

    def test_valid_files_are_not_flagged(self):
        inputs = SimpleNamespace(
            metabolite_maps={"CrPCr": Path("/tmp/crpcr.nii.gz")}, crlb_maps={}, snr_map=None, linewidth_map=None
        )
        with patch("mrsiprep.utils.images.nifti_validity_error", return_value=None):
            self.assertEqual(P._preflight_corrupt_items(inputs, t1_corrupt=False, check_integrity=True), [])


class PreflightTissueLabelTests(unittest.TestCase):
    def test_auto_when_backend_is_not_existing(self):
        layout = MagicMock()
        config = SimpleNamespace(tissue_backend="synthseg-fast")
        self.assertIn("AUTO", P._preflight_tissue_label(layout, "01", "01", config))

    def test_marks_each_probseg_green_or_red(self):
        layout = MagicMock()
        layout.cat12_probseg.side_effect = lambda subject, session, idx: idx != 3  # p3 missing
        config = SimpleNamespace(tissue_backend="existing")
        label = P._preflight_tissue_label(layout, "01", "01", config)
        self.assertIn("[green]p1[/green]", label)
        self.assertIn("[green]p2[/green]", label)
        self.assertIn("[red]p3[/red]", label)


class PreflightTransformStatusTests(unittest.TestCase):
    def test_reports_mrsi_and_anat_by_default(self):
        layout = MagicMock()
        layout.transform.return_value = [Path("/tmp/a"), Path("/tmp/b")]
        config = SimpleNamespace(longitudinal=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "mrsi_to_t1.affine.mat"
            existing.touch()
            layout.transform.return_value = [existing]
            statuses = P._preflight_transform_status(layout, "01", "01", config)
        self.assertEqual(set(statuses), {"mrsi", "anat"})
        self.assertTrue(all(statuses.values()))

    def test_includes_template_stage_when_longitudinal(self):
        layout = MagicMock()
        layout.transform.return_value = []
        config = SimpleNamespace(longitudinal=True)
        statuses = P._preflight_transform_status(layout, "01", "01", config)
        self.assertIn("t1-template", statuses)
        self.assertFalse(statuses["t1-template"])  # no paths -> not present

    def test_missing_files_reported_false(self):
        layout = MagicMock()
        # A path that genuinely does not exist on disk -- no mocking needed.
        layout.transform.return_value = [Path("/tmp/mrsiprep_test_definitely_missing_12345")]
        config = SimpleNamespace(longitudinal=False)
        statuses = P._preflight_transform_status(layout, "01", "01", config)
        self.assertFalse(statuses["mrsi"])


class PreflightFreesurferStatusTests(unittest.TestCase):
    def test_none_when_not_chimera_parcellation(self):
        layout = MagicMock()
        config = SimpleNamespace(parcellation_mode="synthseg")
        self.assertIsNone(P._preflight_freesurfer_status(layout, "01", "01", config))

    def test_false_when_no_raw_t1(self):
        layout = MagicMock()
        layout.raw_t1.return_value = None
        config = SimpleNamespace(parcellation_mode="chimera")
        self.assertFalse(P._preflight_freesurfer_status(layout, "01", "01", config))

    def test_delegates_to_subject_dir_valid_when_raw_t1_present(self):
        layout = MagicMock()
        layout.raw_t1.return_value = Path("/tmp/sub-01_T1w.nii.gz")
        config = SimpleNamespace(parcellation_mode="chimera", freesurfer_dir=Path("/tmp/fs"))
        with patch("mrsiprep.workflows.participant.freesurfer_subject_id", return_value="sub-01"), patch(
            "mrsiprep.workflows.participant.subject_dir_valid", return_value=True
        ) as valid:
            result = P._preflight_freesurfer_status(layout, "01", "01", config)
        self.assertTrue(result)
        valid.assert_called_once_with(Path("/tmp/fs"), "sub-01")


class PreflightTransformColumnsTests(unittest.TestCase):
    def test_two_columns_by_default(self):
        columns = P._preflight_transform_columns(SimpleNamespace(longitudinal=False))
        self.assertEqual([key for key, _ in columns], ["mrsi", "anat"])

    def test_third_column_when_longitudinal(self):
        columns = P._preflight_transform_columns(SimpleNamespace(longitudinal=True))
        self.assertEqual([key for key, _ in columns], ["mrsi", "anat", "t1-template"])


class BuildPreflightTableTests(unittest.TestCase):
    def test_column_count_reflects_optional_sections(self):
        config = SimpleNamespace(longitudinal=False)
        base = P._build_preflight_table(config, P._preflight_transform_columns(config), show_integrity=False, show_freesurfer=False)
        with_extra = P._build_preflight_table(config, P._preflight_transform_columns(config), show_integrity=True, show_freesurfer=True)
        self.assertEqual(len(with_extra.columns), len(base.columns) + 2)


class PreflightRowCellsTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "recording_id": "sub-01",
            "t1": True,
            "mrsi_found": 5,
            "mrsi_expected": 5,
            "crlb_found": 5,
            "snr": True,
            "fwhm": True,
            "brainmask": True,
            "tissue": "[cyan]AUTO[/cyan]",
            "transforms": {"mrsi": True, "anat": False},
            "freesurfer": None,
            "corrupt_items": [],
        }
        row.update(overrides)
        return row

    def test_complete_row_uses_green_counts_and_check_marks(self):
        cells = P._preflight_row_cells(self._row(), [("mrsi", "MRSI->T1"), ("anat", "T1->MNI")], show_integrity=False, show_freesurfer=False)
        self.assertIn("[green]5/5[/green]", cells)
        self.assertIn(P._PREFLIGHT_CHECK_MARK, cells)

    def test_mismatched_mrsi_count_uses_red(self):
        cells = P._preflight_row_cells(self._row(mrsi_found=3), [], show_integrity=False, show_freesurfer=False)
        self.assertIn("[red]3/5[/red]", cells)

    def test_corrupt_items_rendered_when_integrity_shown(self):
        cells = P._preflight_row_cells(self._row(corrupt_items=["T1w"]), [], show_integrity=True, show_freesurfer=False)
        self.assertTrue(any("CORRUPT (T1w)" in cell for cell in cells))

    def test_freesurfer_na_when_none(self):
        cells = P._preflight_row_cells(self._row(freesurfer=None), [], show_integrity=False, show_freesurfer=True)
        self.assertIn(P._PREFLIGHT_NA_MARK, cells)

    def test_transform_columns_use_check_or_proc_mark(self):
        cells = P._preflight_row_cells(self._row(), [("mrsi", "x"), ("anat", "y")], show_integrity=False, show_freesurfer=False)
        self.assertIn(P._PREFLIGHT_CHECK_MARK, cells)
        self.assertIn(P._PREFLIGHT_PROC_MARK, cells)


class PreflightMissingItemsTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {"t1": True, "mrsi_found": 5, "mrsi_expected": 5, "crlb_found": 5, "snr": True, "fwhm": True, "tissue": "[green]p1[/green]"}
        row.update(overrides)
        return row

    def _config(self, **overrides):
        cfg = SimpleNamespace(quality_metrics=["snr", "linewidth", "crlb"], tissue_backend="synthseg-fast")
        for key, value in overrides.items():
            setattr(cfg, key, value)
        return cfg

    def test_no_missing_items_for_a_complete_row(self):
        self.assertEqual(P._preflight_missing_items(self._row(), self._config()), [])

    def test_missing_t1_reported(self):
        self.assertIn("T1w", P._preflight_missing_items(self._row(t1=False), self._config()))

    def test_missing_snr_only_reported_when_required(self):
        row = self._row(snr=False)
        self.assertIn("SNR", P._preflight_missing_items(row, self._config()))
        self.assertNotIn("SNR", P._preflight_missing_items(row, self._config(quality_metrics=["linewidth"])))

    def test_missing_fwhm_only_reported_when_required(self):
        row = self._row(fwhm=False)
        self.assertIn("FWHM", P._preflight_missing_items(row, self._config()))
        self.assertNotIn("FWHM", P._preflight_missing_items(row, self._config(quality_metrics=["snr"])))

    def test_missing_tissue_only_for_existing_backend(self):
        # No longer depends on parcellation_mode at all -- flagged for any
        # config using --tissue-backend existing.
        row = self._row(tissue="[red]p3[/red]")
        self.assertIn("Tissue", P._preflight_missing_items(row, self._config(tissue_backend="existing")))
        self.assertNotIn("Tissue", P._preflight_missing_items(row, self._config(tissue_backend="synthseg-fast")))

    def test_corrupt_items_reported(self):
        row = self._row(corrupt_items=["T1w", "SNR"])
        missing = P._preflight_missing_items(row, self._config())
        self.assertTrue(any("CORRUPT (T1w, SNR)" in item for item in missing))


class CollectRecordingsTests(unittest.TestCase):
    def test_participants_file_takes_precedence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            participants = Path(tmpdir) / "participants.tsv"
            # read_participant_pairs uses csv.DictReader keyed off a header
            # row, and picks "\t" as the delimiter for a .tsv extension.
            participants.write_text("subject\tsession\n01\t01\n02\t\n")
            config = make_config(["/tmp/bids", "/tmp/out", "participant"], participants_file=participants, participant_label=["99"])
            recordings = P.collect_recordings(config)
        self.assertEqual([(r.subject, r.session) for r in recordings], [("01", "01"), ("02", None)])

    def test_participant_and_session_labels_combine_pairwise(self):
        config = make_config(
            ["/tmp/bids", "/tmp/out", "participant"], participants_file=None, participant_label=["01", "02"], session_label=["01", "02"]
        )
        recordings = P.collect_recordings(config)
        self.assertEqual(
            {(r.subject, r.session) for r in recordings}, {("01", "01"), ("01", "02"), ("02", "01"), ("02", "02")}
        )

    def test_participant_labels_without_sessions(self):
        config = make_config(["/tmp/bids", "/tmp/out", "participant"], participants_file=None, participant_label=["01"], session_label=[])
        recordings = P.collect_recordings(config)
        self.assertEqual([(r.subject, r.session) for r in recordings], [("01", None)])

    def test_falls_back_to_bids_discovery(self):
        config = make_config(["/tmp/bids", "/tmp/out", "participant"], participants_file=None, participant_label=[], session_label=[])
        discovered = [Recording("03", "01")]
        with patch("mrsiprep.workflows.participant.BIDSLayout") as layout_cls:
            layout_cls.return_value.discover_recordings.return_value = discovered
            recordings = P.collect_recordings(config)
        self.assertEqual(recordings, discovered)


class ValidateBackendInputsTests(unittest.TestCase):
    def test_synthseg_fast_backend_requires_raw_t1(self):
        # synthseg-fast is the default tissue_backend, so a default config
        # already exercises this without any explicit override.
        config = make_config(["/tmp/bids", "/tmp/out", "participant"])
        with patch("mrsiprep.workflows.participant.BIDSLayout") as layout_cls:
            layout_cls.return_value.raw_t1.return_value = None
            with self.assertRaisesRegex(FileNotFoundError, "synthseg-fast"):
                P._validate_backend_inputs(config, "01", "01")

    def test_custom_atlas_requires_both_files(self):
        config = make_config(
            ["/tmp/bids", "/tmp/out", "participant", "--parcellation-mode", "atlas", "--atlas", "custom"],
            custom_atlas=None,
            custom_atlas_lut=None,
        )
        with patch("mrsiprep.workflows.participant.BIDSLayout") as layout_cls:
            layout_cls.return_value.raw_t1.return_value = Path("/tmp/t1.nii.gz")
            with self.assertRaisesRegex(FileNotFoundError, "--custom-atlas is required"):
                P._validate_backend_inputs(config, "01", "01")

    def test_custom_atlas_lut_required_even_when_custom_atlas_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_atlas = Path(tmpdir) / "atlas.nii.gz"
            custom_atlas.touch()
            config = make_config(
                ["/tmp/bids", "/tmp/out", "participant", "--parcellation-mode", "atlas", "--atlas", "custom"],
                custom_atlas=custom_atlas,
                custom_atlas_lut=None,
            )
            with patch("mrsiprep.workflows.participant.BIDSLayout") as layout_cls:
                layout_cls.return_value.raw_t1.return_value = Path("/tmp/t1.nii.gz")
                with self.assertRaisesRegex(FileNotFoundError, "--custom-atlas-lut is required"):
                    P._validate_backend_inputs(config, "01", "01")

    def test_passes_when_all_requirements_met(self):
        config = make_config(["/tmp/bids", "/tmp/out", "participant"])
        with patch("mrsiprep.workflows.participant.BIDSLayout") as layout_cls:
            layout_cls.return_value.raw_t1.return_value = Path("/tmp/t1.nii.gz")
            P._validate_backend_inputs(config, "01", "01")  # must not raise


class RunParticipantWorkflowTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.config = make_config(["/tmp/bids", str(self.tmp / "out"), "participant"])
        self._patches = [
            patch("mrsiprep.workflows.participant.ensure_work_dirs"),
            patch("mrsiprep.workflows.participant.init_derivative"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_returns_empty_list_when_no_recordings_match(self):
        with patch("mrsiprep.workflows.participant.collect_recordings", return_value=[]):
            self.assertEqual(P.run_participant_workflow(self.config), [])

    def test_skipped_recordings_are_excluded_from_dispatch(self):
        recordings = [Recording("01", "01"), Recording("02", "01")]
        with patch("mrsiprep.workflows.participant.collect_recordings", return_value=recordings), patch(
            "mrsiprep.workflows.participant._gather_input_availability", return_value={}
        ), patch("mrsiprep.workflows.participant._render_preflight_table"), patch(
            "mrsiprep.workflows.participant.validate_recording", side_effect=[(Path("t1"), object()), P.ValidationError("bad")]
        ), patch(
            "mrsiprep.workflows.participant._validate_backend_inputs"
        ), patch(
            "mrsiprep.workflows.nipype_engine.run.execute_recordings_nipype",
            return_value=[P.RecordingStatus("01", "01", "success")],
        ) as execute_mock:
            statuses = P.run_participant_workflow(self.config)

        ready_arg = execute_mock.call_args[0][1]
        self.assertEqual([(r.subject, r.session) for r in ready_arg], [("01", "01")])
        self.assertEqual([s.status for s in statuses], ["skipped", "success"])

    def test_longitudinal_builds_subject_templates_before_dispatch(self):
        recordings = [Recording("01", "01")]
        self.config.longitudinal = True
        with patch("mrsiprep.workflows.participant.collect_recordings", return_value=recordings), patch(
            "mrsiprep.workflows.participant._gather_input_availability", return_value={}
        ), patch("mrsiprep.workflows.participant._render_preflight_table"), patch(
            "mrsiprep.workflows.participant.validate_recording", return_value=(Path("t1"), object())
        ), patch(
            "mrsiprep.workflows.participant._validate_backend_inputs"
        ), patch(
            "mrsiprep.workflows.participant._build_subject_templates", return_value={"01": "template"}
        ) as build_templates, patch(
            "mrsiprep.workflows.nipype_engine.run.execute_recordings_nipype", return_value=[]
        ) as execute_mock:
            P.run_participant_workflow(self.config)

        build_templates.assert_called_once()
        self.assertEqual(execute_mock.call_args.kwargs["subject_templates"], {"01": "template"})

    def test_no_ready_recordings_skips_dispatch_entirely(self):
        recordings = [Recording("01", "01")]
        with patch("mrsiprep.workflows.participant.collect_recordings", return_value=recordings), patch(
            "mrsiprep.workflows.participant._gather_input_availability", return_value={}
        ), patch("mrsiprep.workflows.participant._render_preflight_table"), patch(
            "mrsiprep.workflows.participant.validate_recording", side_effect=P.ValidationError("bad")
        ), patch("mrsiprep.workflows.nipype_engine.run.execute_recordings_nipype") as execute_mock:
            statuses = P.run_participant_workflow(self.config)

        execute_mock.assert_not_called()
        self.assertEqual(statuses[0].status, "skipped")


class ValidateParticipantInputsTests(unittest.TestCase):
    def test_success_and_failure_outcomes_are_both_reported(self):
        config = make_config(["/tmp/bids", "/tmp/out", "participant"])
        recordings = [Recording("01", "01"), Recording("02", "01")]
        good_inputs = SimpleNamespace(metabolite_maps={"CrPCr": "x"}, snr_map="snr", linewidth_map="fwhm", brainmask="mask")
        with patch("mrsiprep.workflows.participant.collect_recordings", return_value=recordings), patch(
            "mrsiprep.workflows.participant._gather_input_availability", return_value={}
        ), patch("mrsiprep.workflows.participant._render_preflight_table"), patch(
            "mrsiprep.workflows.participant.validate_recording",
            side_effect=[(Path("t1"), good_inputs), P.ValidationError("bad")],
        ), patch("mrsiprep.workflows.participant._validate_backend_inputs"):
            statuses = P.validate_participant_inputs(config)

        self.assertEqual([s.status for s in statuses], ["success", "failed"])
        self.assertEqual(statuses[0].outputs["metabolites"], ["CrPCr"])
        self.assertIsNotNone(statuses[1].error)


class RunReportsOnlyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.config = make_config(["/tmp/bids", str(self.tmp / "out"), "participant"])
        self._patches = [
            patch("mrsiprep.workflows.participant.ensure_work_dirs"),
            patch("mrsiprep.workflows.participant.init_derivative"),
            patch("mrsiprep.workflows.participant.collect_recordings", return_value=[Recording("01", "01")]),
            patch("mrsiprep.workflows.participant._gather_input_availability", return_value={}),
            patch("mrsiprep.workflows.participant._render_preflight_table"),
            patch("mrsiprep.workflows.participant.validate_recording", return_value=(Path("t1"), object())),
            patch("mrsiprep.workflows.participant._validate_backend_inputs"),
            patch("mrsiprep.utils.runtime_metrics.write_runtime_metrics"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_all_steps_succeed_yields_success_status_with_outputs(self):
        def step_one(config, subject, session, ctx):
            ctx = dict(ctx)
            ctx["outputs"] = {"report": "ok"}
            return ctx

        with patch("mrsiprep.workflows.nipype_engine.nodes.STEP_SEQUENCE", [("step_one", step_one)]):
            statuses = P.run_reports_only_workflow(self.config)

        self.assertEqual(statuses[0].status, "success")
        self.assertEqual(statuses[0].outputs, {"report": "ok"})

    def test_step_exception_yields_failed_status_and_continues(self):
        def failing_step(config, subject, session, ctx):
            raise RuntimeError("boom")

        with patch("mrsiprep.workflows.nipype_engine.nodes.STEP_SEQUENCE", [("failing_step", failing_step)]):
            statuses = P.run_reports_only_workflow(self.config)

        self.assertEqual(statuses[0].status, "failed")
        self.assertIn("boom", statuses[0].error)

    def test_stop_on_first_crash_reraises_instead_of_continuing(self):
        self.config.stop_on_first_crash = True

        def failing_step(config, subject, session, ctx):
            raise RuntimeError("boom")

        with patch("mrsiprep.workflows.nipype_engine.nodes.STEP_SEQUENCE", [("failing_step", failing_step)]):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                P.run_reports_only_workflow(self.config)


if __name__ == "__main__":
    unittest.main()

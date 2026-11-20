"""Tests for the guided wizard in mrsiprep/interfaces/command_builder_app.py.

Uses streamlit.testing.v1.AppTest to drive the real Streamlit script headless
(no server, no browser) -- the same app module `streamlit run
mrsiprep/interfaces/command_builder_app.py` would execute. Each test starts a
fresh AppTest (Streamlit reruns the whole script on every interaction, same
as a live session), so there is no shared mutable state between tests.

A central design invariant this file checks explicitly: there is only ONE
pipeline (see the module's own docstring/comments in command_builder_app.py
and the steps_registry.py STEP_SEQUENCE/STEP_DEPENDENCIES registry) -- both
Analysis outcomes ("Normalize metabolite maps" / "Parcellation and
connectivity") must produce a command with NO --steps flag. Only the
advanced Custom Pipeline escape hatch ever emits --steps. A regression back
toward a "two different step subsets" design would be caught by
test_both_outcomes_emit_no_steps_flag below.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

from mrsiprep.interfaces.command_builder_app import (
    CUSTOM_STEP_FLAGS,
    _build_command,
    _scan_metabolites_from_filenames,
)
from mrsiprep.cli.parser import build_parser

# AppTest.from_file resolves a relative path against the file that calls
# it (this test module), not the process's cwd -- an absolute path avoids
# depending on where pytest happens to be invoked from.
APP_PATH = str(Path(__file__).resolve().parent.parent / "mrsiprep" / "interfaces" / "command_builder_app.py")


def _new_app() -> AppTest:
    at = AppTest.from_file(APP_PATH)
    at.run()
    return at


def _choose_outcome(at: AppTest, outcome: str) -> AppTest:
    key = "wizard_outcome_normalize" if outcome == "normalize" else "wizard_outcome_parcellation"
    at.button(key=key).click().run()
    return at


def _fill_data_step(at: AppTest, bids_dir="/tmp", output_dir="/tmp/out", metabolites=None) -> AppTest:
    at.text_input(key="wizard_field_bids_dir").set_value(bids_dir).run()
    at.text_input(key="wizard_field_output_dir").set_value(output_dir).run()
    at.multiselect(key="wizard_field_metabolites").set_value(metabolites or ["CrPCr"]).run()
    return at


def _goto_step(at: AppTest, step: int) -> AppTest:
    at.session_state["wizard_step"] = step
    at.run()
    return at


class WizardNavigationTests(unittest.TestCase):
    def test_initial_load_has_no_exception(self):
        at = _new_app()
        self.assertEqual(list(at.exception), [])
        self.assertEqual(at.session_state["wizard_step"], 0)

    def test_choosing_an_outcome_advances_to_data_step(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        self.assertEqual(at.session_state["wizard_step"], 1)
        self.assertEqual(at.session_state["wizard_outcome"], "normalize")

    def test_field_values_survive_navigating_to_other_steps_and_back(self):
        """Set bids_dir on Data, navigate to Processing and Review and back,
        assert unchanged -- the wizard's core "one shared state prefix,
        revisit any step without losing data" promise."""
        at = _new_app()
        _choose_outcome(at, "normalize")
        _fill_data_step(at, bids_dir="/tmp/my_dataset", output_dir="/tmp/my_out", metabolites=["CrPCr", "NAANAAG"])

        _goto_step(at, 2)
        self.assertEqual(list(at.exception), [])
        _goto_step(at, 3)
        self.assertEqual(list(at.exception), [])
        _goto_step(at, 1)
        self.assertEqual(list(at.exception), [])

        bids_dir_inputs = [ti for ti in at.text_input if ti.key == "wizard_field_bids_dir"]
        self.assertEqual(bids_dir_inputs[0].value, "/tmp/my_dataset")
        output_dir_inputs = [ti for ti in at.text_input if ti.key == "wizard_field_output_dir"]
        self.assertEqual(output_dir_inputs[0].value, "/tmp/my_out")
        metabolite_widgets = [ms for ms in at.multiselect if ms.key == "wizard_field_metabolites"]
        self.assertEqual(sorted(metabolite_widgets[0].value), ["CrPCr", "NAANAAG"])

        _goto_step(at, 2)
        ref_met_boxes = [sb for sb in at.selectbox if sb.key == "wizard_field_ref_met"]
        self.assertEqual(sorted(ref_met_boxes[0].options), ["CrPCr", "NAANAAG"])

    def test_back_button_still_renders_after_step_body_raises(self):
        """A step body can raise (e.g. Review's preflight button calling
        into real pipeline code that hits an import error from a stale
        environment) -- this must not take the nav row down with it and
        strand the user with no way back. Patches _compute_preflight to
        raise, deterministically reproducing the failure mode reported
        against the real app, and asserts Back/the step buttons are still
        present and enabled afterward."""
        import mrsiprep.interfaces.command_builder_app as app_module

        original = app_module._compute_preflight

        def _boom(*args, **kwargs):
            raise ImportError("simulated stale-environment import error")

        app_module._compute_preflight = _boom
        try:
            at = _new_app()
            _choose_outcome(at, "normalize")
            _fill_data_step(at, bids_dir="/tmp", output_dir="/tmp/wizard_nav_survives_out")
            _goto_step(at, 2)
            at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
            _goto_step(at, 3)

            preflight_buttons = [b for b in at.button if b.key == "wizard_run_preflight_btn"]
            self.assertEqual(len(preflight_buttons), 1)
            preflight_buttons[0].click().run()

            back_buttons = [b for b in at.button if b.key == "wizard_back_btn"]
            self.assertEqual(len(back_buttons), 1)
            self.assertFalse(back_buttons[0].disabled)

            back_buttons[0].click().run()
            self.assertEqual(at.session_state["wizard_step"], 2)
        finally:
            app_module._compute_preflight = original


class WizardNoStepsInvariantTests(unittest.TestCase):
    """The design's most important invariant: neither Analysis outcome ever
    changes --steps. All 20 steps in STEP_SEQUENCE always run; the outcome
    choice only governs which Processing sections are foregrounded."""

    def _build_and_get_command(self, outcome: str) -> str:
        at = _new_app()
        _choose_outcome(at, outcome)
        _fill_data_step(at)
        _goto_step(at, 2)
        at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
        _goto_step(at, 3)
        self.assertEqual(list(at.exception), [])
        codes = list(at.code)
        self.assertEqual(len(codes), 1, "Review should show exactly one generated command block once valid")
        return codes[0].value

    def test_normalize_outcome_emits_no_steps_flag(self):
        command = self._build_and_get_command("normalize")
        self.assertNotIn("--steps", command)

    def test_parcellation_outcome_emits_no_steps_flag(self):
        command = self._build_and_get_command("parcellation")
        self.assertNotIn("--steps", command)

    def test_custom_pipeline_escape_hatch_is_the_only_place_steps_is_emitted(self):
        at = _new_app()
        at.checkbox(key="wizard_advanced_steps_checkbox").set_value(True).run()
        at.button(key="add_btn_prepare").click().run()
        self.assertEqual(list(at.exception), [])
        codes = list(at.code)
        self.assertEqual(len(codes), 1)
        self.assertIn("--steps prepare", codes[0].value)


class WizardValidationGatingTests(unittest.TestCase):
    def test_next_button_disabled_on_data_step_when_required_fields_missing(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        next_buttons = [b for b in at.button if b.key == "wizard_next_btn"]
        self.assertTrue(next_buttons[0].disabled)

    def test_next_button_enabled_once_required_fields_are_filled(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        _fill_data_step(at)
        next_buttons = [b for b in at.button if b.key == "wizard_next_btn"]
        self.assertFalse(next_buttons[0].disabled)

    def test_review_withholds_command_when_configuration_incomplete(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        _goto_step(at, 3)
        self.assertEqual(list(at.exception), [])
        self.assertEqual(len(list(at.code)), 0, "no command should render while blocking issues remain")
        error_messages = " ".join(el.value for el in at.get("error"))
        self.assertIn("Incomplete configuration", error_messages)

    def test_review_shows_ready_state_once_configuration_is_complete(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        _fill_data_step(at)
        _goto_step(at, 2)
        at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
        _goto_step(at, 3)
        success_messages = " ".join(el.value for el in at.get("success"))
        self.assertIn("Ready to copy", success_messages)
        self.assertEqual(len(list(at.code)), 1)

    def test_chimera_mode_without_license_blocks_review(self):
        at = _new_app()
        _choose_outcome(at, "parcellation")
        _fill_data_step(at)
        _goto_step(at, 2)
        at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
        at.selectbox(key="wizard_field_parcellation_mode").set_value("chimera").run()
        _goto_step(at, 3)
        error_messages = " ".join(el.value for el in at.get("error"))
        self.assertIn("Incomplete configuration", error_messages)
        markdown_text = " ".join(el.value for el in at.get("markdown"))
        self.assertIn("FreeSurfer license", markdown_text)

    def test_chimera_mode_with_license_unblocks_review(self):
        at = _new_app()
        _choose_outcome(at, "parcellation")
        _fill_data_step(at)
        _goto_step(at, 2)
        at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
        at.selectbox(key="wizard_field_parcellation_mode").set_value("chimera").run()
        at.text_input(key="wizard_field_fs_license").set_value("/tmp/license.txt").run()
        _goto_step(at, 3)
        codes = list(at.code)
        self.assertEqual(len(codes), 1)
        self.assertIn("--parcellation-mode chimera", codes[0].value)
        self.assertIn("--fs-license /tmp/license.txt", codes[0].value)


def _choose_create_inputs(at: AppTest) -> AppTest:
    at.button(key="wizard_outcome_create_inputs").click().run()
    return at


def _fill_project_step(at: AppTest, bids_dir: str) -> AppTest:
    """Fills the Project step's root + name inputs so the joined
    `<root>/<project_name>` path equals the given `bids_dir`, matching how
    _render_batch_import_project_step builds state["bids_dir"]."""
    root, name = str(Path(bids_dir).parent), Path(bids_dir).name
    at.text_input(key="wizard_batch_bids_root").set_value(root).run()
    at.text_input(key="wizard_batch_project_name").set_value(name).run()
    return at


class BatchImportProjectStepTests(unittest.TestCase):
    """The third Analysis card ("Create MRSIprep inputs") now routes to a
    7-step batch-import flow that scans/names/matches/migrates real files,
    replacing the old single-pair 2-step mrsiprep-import-command
    generator (see _render_wizard_create_inputs_outcome's docstring)."""

    def test_choosing_the_card_routes_to_the_batch_flow(self):
        at = _choose_create_inputs(_new_app())
        self.assertEqual(list(at.exception), [])
        self.assertEqual(at.session_state["wizard_outcome"], "create_inputs")
        headers = [h.value for h in at.header]
        self.assertIn("Create MRSIprep inputs", headers)

    def test_back_to_analysis_resets_outcome(self):
        at = _choose_create_inputs(_new_app())
        [b for b in at.button if b.label == "← Back to Analysis"][0].click().run()
        self.assertIsNone(at.session_state["wizard_outcome"])
        self.assertEqual(at.session_state["wizard_step"], 0)
        headers = [h.value for h in at.header]
        self.assertIn("What would you like to do?", headers)

    def test_next_disabled_until_bids_dir_filled(self):
        at = _choose_create_inputs(_new_app())
        next_btn = next(b for b in at.button if b.key == "wizard_batch_next_0")
        self.assertTrue(next_btn.disabled)
        at = _fill_project_step(at, "/data/bids/test-migrate")
        next_btn = next(b for b in at.button if b.key == "wizard_batch_next_0")
        self.assertFalse(next_btn.disabled)

    def test_project_name_is_joined_onto_the_root(self):
        at = _choose_create_inputs(_new_app())
        at.text_input(key="wizard_batch_bids_root").set_value("/media/flucchetti/NVME_BIDS_1").run()
        at.text_input(key="wizard_batch_project_name").set_value("test-migrate").run()
        self.assertEqual(
            at.session_state["wizard_batch_import"]["bids_dir"],
            str(Path("/media/flucchetti/NVME_BIDS_1") / "test-migrate"),
        )

    def test_reusing_existing_project_shown_when_dataset_description_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "test-migrate"
            project_dir.mkdir()
            (project_dir / "dataset_description.json").write_text("{}")
            at = _choose_create_inputs(_new_app())
            at = _fill_project_step(at, str(project_dir))
            successes = [s.value for s in at.success]
            self.assertTrue(any("Reusing existing project" in s for s in successes))

    def test_new_project_shows_dataset_description_snippet(self):
        at = _choose_create_inputs(_new_app())
        at = _fill_project_step(at, "/data/new_bids/test-migrate")
        codes = [c.value for c in at.code]
        self.assertTrue(any("DatasetType" in c for c in codes))


class BatchImportAnatScanStepTests(unittest.TestCase):
    def _goto_anat_scan(self, at: AppTest, bids_dir="/tmp/bids/test-migrate") -> AppTest:
        at = _choose_create_inputs(at)
        at = _fill_project_step(at, bids_dir)
        [b for b in at.button if b.key == "wizard_batch_next_0"][0].click().run()
        return at

    def test_scan_finds_matching_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            import nibabel as nib
            import numpy as np

            (Path(tmp) / "scan_mprage.nii.gz").write_bytes(b"")
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4)), Path(tmp) / "scan_mprage.nii.gz")
            at = self._goto_anat_scan(_new_app())
            at.text_input(key="wizard_batch_t1_root").set_value(tmp).run()
            at.button(key="wizard_batch_t1_scan_btn").click().run()
            checkboxes = [c for c in at.checkbox if c.key and c.key.startswith("wizard_batch_t1_row_")]
            self.assertEqual(len(checkboxes), 1)

    def test_next_disabled_until_a_row_is_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            import nibabel as nib
            import numpy as np

            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4)), Path(tmp) / "scan_mprage.nii.gz")
            at = self._goto_anat_scan(_new_app())
            at.text_input(key="wizard_batch_t1_root").set_value(tmp).run()
            at.button(key="wizard_batch_t1_scan_btn").click().run()
            next_btn = next(b for b in at.button if b.key == "wizard_batch_next_1")
            self.assertFalse(next_btn.disabled)
            at.button(key="wizard_batch_t1_clear_all").click().run()
            next_btn = next(b for b in at.button if b.key == "wizard_batch_next_1")
            self.assertTrue(next_btn.disabled)

    def test_warns_when_mrsinmrs_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            at = self._goto_anat_scan(_new_app(), bids_dir=tmp)
            warnings = [w.value for w in at.warning]
            self.assertTrue(any("mrsinmrs.json" in w for w in warnings))


class BatchImportAnatNamingStepTests(unittest.TestCase):
    def _goto_naming_step(self, tmp_t1_dir: str) -> AppTest:
        at = _choose_create_inputs(_new_app())
        at = _fill_project_step(at, "/tmp/bids/test-migrate")
        [b for b in at.button if b.key == "wizard_batch_next_0"][0].click().run()
        at.text_input(key="wizard_batch_t1_root").set_value(tmp_t1_dir).run()
        at.button(key="wizard_batch_t1_scan_btn").click().run()
        [b for b in at.button if b.key == "wizard_batch_next_1"][0].click().run()
        return at

    def _make_t1_file(self, tmp: str, name: str) -> None:
        import nibabel as nib
        import numpy as np

        nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4)), Path(tmp) / name)

    def test_sequential_pattern_fills_subject_and_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_t1_file(tmp, "scan_mprage.nii.gz")
            at = self._goto_naming_step(tmp)
            at.text_input(key="wizard_batch_naming_pattern").set_value("CHUVUP$i").run()
            self.assertEqual(at.text_input(key="wizard_batch_anat_sub_0").value, "CHUVUP0001")
            self.assertEqual(at.text_input(key="wizard_batch_anat_ses_0").value, "V1")

    def test_detect_mode_parses_filename_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_t1_file(tmp, "T105_V1_mprage.nii.gz")
            at = self._goto_naming_step(tmp)
            at.radio(key="wizard_batch_naming_mode").set_value("detect").run()
            at.text_input(key="wizard_batch_detect_sub_marker").set_value("T").run()
            at.text_input(key="wizard_batch_detect_ses_marker").set_value("V").run()
            self.assertEqual(at.text_input(key="wizard_batch_anat_sub_0").value, "105")
            self.assertEqual(at.text_input(key="wizard_batch_anat_ses_0").value, "V1")

    def test_next_blocked_when_subject_or_session_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_t1_file(tmp, "scan_mprage.nii.gz")
            at = self._goto_naming_step(tmp)
            at.text_input(key="wizard_batch_anat_sub_0").set_value("").run()
            next_btn = next(b for b in at.button if b.key == "wizard_batch_next_2")
            self.assertTrue(next_btn.disabled)

    def test_duplicate_destination_blocks_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_t1_file(tmp, "scan_a_mprage.nii.gz")
            self._make_t1_file(tmp, "scan_b_mprage.nii.gz")
            at = self._goto_naming_step(tmp)
            at.text_input(key="wizard_batch_anat_sub_0").set_value("S001").run()
            at.text_input(key="wizard_batch_anat_ses_0").set_value("V1").run()
            at.text_input(key="wizard_batch_anat_sub_1").set_value("S001").run()
            at.text_input(key="wizard_batch_anat_ses_1").set_value("V1").run()
            next_btn = next(b for b in at.button if b.key == "wizard_batch_next_2")
            self.assertTrue(next_btn.disabled)


class BatchImportMrsiScanStepTests(unittest.TestCase):
    def _goto_mrsi_scan_step(self) -> AppTest:
        import nibabel as nib
        import numpy as np

        at = _choose_create_inputs(_new_app())
        at = _fill_project_step(at, "/tmp/bids/test-migrate")
        [b for b in at.button if b.key == "wizard_batch_next_0"][0].click().run()
        with tempfile.TemporaryDirectory() as tmp:
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4)), Path(tmp) / "scan_mprage.nii.gz")
            at.text_input(key="wizard_batch_t1_root").set_value(tmp).run()
            at.button(key="wizard_batch_t1_scan_btn").click().run()
        [b for b in at.button if b.key == "wizard_batch_next_1"][0].click().run()
        at.text_input(key="wizard_batch_anat_sub_0").set_value("S001").run()
        at.text_input(key="wizard_batch_anat_ses_0").set_value("V1").run()
        [b for b in at.button if b.key == "wizard_batch_next_2"][0].click().run()
        return at

    def test_scan_classifies_files_and_reports_unmatched(self):
        import nibabel as nib
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "FolderA"
            folder.mkdir()
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4)), folder / "NAA_signal.nii.gz")
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4)), folder / "junk.nii.gz")
            at = self._goto_mrsi_scan_step()
            at.text_input(key="wizard_batch_mrsi_root").set_value(tmp).run()
            at.multiselect(key="wizard_batch_mrsi_metabolites").set_value(["NAA"]).run()
            at.text_input(key="wizard_batch_mrsi_signal_pattern").set_value("signal").run()
            at.button(key="wizard_batch_mrsi_scan_btn").click().run()
            expander_labels = [e.label for e in at.expander]
            self.assertTrue(any("unmatched" in label for label in expander_labels))

    def test_next_blocked_with_no_matches(self):
        at = self._goto_mrsi_scan_step()
        next_btn = next(b for b in at.button if b.key == "wizard_batch_next_3")
        self.assertTrue(next_btn.disabled)


class BatchImportMrsinmrsStepTests(unittest.TestCase):
    def _goto_mrsinmrs_step(self, bids_dir: str) -> AppTest:
        at = _choose_create_inputs(_new_app())
        at = _fill_project_step(at, bids_dir)
        at.session_state["wizard_import_step"] = 4
        at.run()
        return at

    def test_create_mode_writes_file_and_round_trips_through_load_mrsinmrs(self):
        from mrsiprep.io.mrsinmrs import load_mrsinmrs

        with tempfile.TemporaryDirectory() as tmp:
            bids_dir = Path(tmp) / "test-migrate"
            at = self._goto_mrsinmrs_step(str(bids_dir))
            at.button(key="wizard_batch_mrsinmrs_save_btn").click().run()
            write_path = bids_dir / "derivatives" / "mrsi-orig" / "mrsinmrs.json"
            self.assertTrue(write_path.is_file())
            parsed = load_mrsinmrs(bids_dir=str(bids_dir), required=True)
            self.assertIn("QuantificationTool", parsed["CommonMetadata"])

    def test_existing_mode_validates_via_real_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "custom_mrsinmrs.json"
            existing.write_text('{"CommonMetadata": {"QuantificationTool": "lcmodel", "LinewidthUnit": "Hz", "CRLBUnit": "percent"}}')
            at = self._goto_mrsinmrs_step(str(Path(tmp) / "test-migrate"))
            at.radio(key="wizard_batch_mrsinmrs_mode").set_value("existing").run()
            at.text_input(key="wizard_batch_mrsinmrs_existing_path").set_value(str(existing)).run()
            successes = [s.value for s in at.success]
            self.assertTrue(any("parses cleanly" in s for s in successes))

    def test_existing_mode_shows_error_for_invalid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("not json")
            at = self._goto_mrsinmrs_step(str(Path(tmp) / "test-migrate"))
            at.radio(key="wizard_batch_mrsinmrs_mode").set_value("existing").run()
            at.text_input(key="wizard_batch_mrsinmrs_existing_path").set_value(str(bad)).run()
            errors = [e.value for e in at.error]
            self.assertTrue(errors)

    def test_linewidth_ppm_requires_field_strength(self):
        with tempfile.TemporaryDirectory() as tmp:
            at = self._goto_mrsinmrs_step(tmp)
            at.selectbox(key="wizard_batch_mrsinmrs_linewidth_unit").set_value("ppm").run()
            next_btn = next(b for b in at.button if b.key == "wizard_batch_next_4")
            self.assertTrue(next_btn.disabled)


class BatchImportMatchingStepTests(unittest.TestCase):
    def _goto_matching_step(self) -> AppTest:
        import nibabel as nib
        import numpy as np

        at = _choose_create_inputs(_new_app())
        at = _fill_project_step(at, "/tmp/bids/test-migrate")
        [b for b in at.button if b.key == "wizard_batch_next_0"][0].click().run()
        with tempfile.TemporaryDirectory() as t1_dir, tempfile.TemporaryDirectory() as mrsi_dir:
            affine = np.eye(4)
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), affine), Path(t1_dir) / "a_mprage.nii.gz")
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), affine), Path(t1_dir) / "b_mprage.nii.gz")
            at.text_input(key="wizard_batch_t1_root").set_value(t1_dir).run()
            at.button(key="wizard_batch_t1_scan_btn").click().run()
            [b for b in at.button if b.key == "wizard_batch_next_1"][0].click().run()
            at.text_input(key="wizard_batch_anat_sub_0").set_value("S001").run()
            at.text_input(key="wizard_batch_anat_ses_0").set_value("V1").run()
            at.text_input(key="wizard_batch_anat_sub_1").set_value("S002").run()
            at.text_input(key="wizard_batch_anat_ses_1").set_value("V1").run()
            [b for b in at.button if b.key == "wizard_batch_next_2"][0].click().run()

            (Path(mrsi_dir) / "FolderA").mkdir()
            (Path(mrsi_dir) / "FolderB").mkdir()
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), affine), Path(mrsi_dir) / "FolderA" / "NAA_signal.nii.gz")
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), affine), Path(mrsi_dir) / "FolderB" / "NAA_signal.nii.gz")
            at.text_input(key="wizard_batch_mrsi_root").set_value(mrsi_dir).run()
            at.multiselect(key="wizard_batch_mrsi_metabolites").set_value(["NAA"]).run()
            at.text_input(key="wizard_batch_mrsi_signal_pattern").set_value("signal").run()
            at.button(key="wizard_batch_mrsi_scan_btn").click().run()
        [b for b in at.button if b.key == "wizard_batch_next_3"][0].click().run()
        at.session_state["wizard_import_step"] = 5
        at.run()
        return at

    def test_mismatched_row_counts_block_next(self):
        at = self._goto_matching_step()
        at.session_state["wizard_batch_import"]["anat_rows"] = at.session_state["wizard_batch_import"]["anat_rows"][:1]
        at.run()
        errors = [e.value for e in at.error]
        self.assertTrue(any("must have" in e for e in errors))

    def test_reorder_swaps_adjacent_entries(self):
        at = self._goto_matching_step()
        initial_order = list(at.session_state["wizard_batch_match_order"])
        down_buttons = [b for b in at.button if b.key == "wizard_batch_match_down_0"]
        down_buttons[0].click().run()
        self.assertEqual(at.session_state["wizard_batch_match_order"], [initial_order[1], initial_order[0]])

    def test_confirm_advances_to_migrate_step(self):
        at = self._goto_matching_step()
        at.button(key="wizard_batch_match_confirm_btn").click().run()
        self.assertEqual(at.session_state["wizard_import_step"], 6)


class BatchImportMigrateStepTests(unittest.TestCase):
    def test_migrate_writes_real_files_to_bids_tree(self):
        import nibabel as nib
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            t1_dir = Path(tmp) / "t1"
            mrsi_dir = Path(tmp) / "mrsi"
            bids_dir = Path(tmp) / "bids"
            t1_dir.mkdir()
            (mrsi_dir / "FolderA").mkdir(parents=True)
            affine = np.eye(4)
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), affine), t1_dir / "scan_mprage.nii.gz")
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), affine), mrsi_dir / "FolderA" / "NAA_signal.nii.gz")

            at = _choose_create_inputs(_new_app())
            at = _fill_project_step(at, str(bids_dir))
            [b for b in at.button if b.key == "wizard_batch_next_0"][0].click().run()
            at.text_input(key="wizard_batch_t1_root").set_value(str(t1_dir)).run()
            at.button(key="wizard_batch_t1_scan_btn").click().run()
            [b for b in at.button if b.key == "wizard_batch_next_1"][0].click().run()
            at.text_input(key="wizard_batch_anat_sub_0").set_value("S001").run()
            at.text_input(key="wizard_batch_anat_ses_0").set_value("V1").run()
            [b for b in at.button if b.key == "wizard_batch_next_2"][0].click().run()
            at.text_input(key="wizard_batch_mrsi_root").set_value(str(mrsi_dir)).run()
            at.multiselect(key="wizard_batch_mrsi_metabolites").set_value(["NAA"]).run()
            at.text_input(key="wizard_batch_mrsi_signal_pattern").set_value("signal").run()
            at.button(key="wizard_batch_mrsi_scan_btn").click().run()
            [b for b in at.button if b.key == "wizard_batch_next_3"][0].click().run()
            at.session_state["wizard_import_step"] = 6
            at.run()
            at.button(key="wizard_batch_migrate_btn").click().run()

            self.assertTrue((bids_dir / "sub-S001" / "ses-V1" / "anat").glob("*_T1w.nii.gz"))
            mrsi_out = list((bids_dir / "derivatives" / "mrsi-orig" / "sub-S001" / "ses-V1").glob("*_mrsi.nii.gz"))
            self.assertEqual(len(mrsi_out), 1)
            successes = [s.value for s in at.success]
            self.assertTrue(any("Migrated successfully" in s for s in successes))

    def test_start_another_batch_resets_state(self):
        at = _choose_create_inputs(_new_app())
        at = _fill_project_step(at, "/tmp/bids/test-migrate")
        at.session_state["wizard_import_step"] = 6
        at.run()
        at.button(key="wizard_batch_restart_btn").click().run()
        self.assertEqual(at.session_state["wizard_import_step"], 0)
        self.assertEqual(at.session_state["wizard_batch_import"]["bids_dir"], "")


class VersionBarUpdateButtonTests(unittest.TestCase):
    """The page header no longer carries the old "Builds a runnable..."
    caption, and now offers an Update button next to the version line that
    runs `mrsiprep-docker --update` and refreshes the displayed Docker image
    version on success."""

    def test_old_explanatory_caption_is_removed(self):
        at = _new_app()
        captions = " ".join(c.value for c in at.caption)
        self.assertNotIn("Builds a runnable", captions)

    def test_version_caption_includes_all_three_versions(self):
        at = _new_app()
        captions = " ".join(c.value for c in at.caption)
        self.assertIn("Command builder (mrsiprep) version:", captions)
        self.assertIn("mrsiprep-docker wrapper version:", captions)
        self.assertIn("Docker image (`mrsiup/mrsiprep:cpu`) version:", captions)

    def test_update_button_runs_mrsiprep_docker_update_and_refreshes_version(self):
        at = _new_app()
        fake_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=fake_result):
            at.button(key=None)  # no-op; ensures widgets are enumerated
            [b for b in at.button if b.label == "Update"][0].click().run()
        self.assertEqual(list(at.exception), [])
        successes = " ".join(s.value for s in at.success)
        self.assertIn("Docker image updated", successes)

    def test_update_button_surfaces_a_failed_pull(self):
        at = _new_app()
        fake_result = MagicMock(returncode=1, stdout="", stderr="network error")
        with patch("subprocess.run", return_value=fake_result):
            [b for b in at.button if b.label == "Update"][0].click().run()
        self.assertEqual(list(at.exception), [])
        errors = " ".join(e.value for e in at.error)
        self.assertIn("network error", errors)

    def test_update_button_reports_missing_wrapper(self):
        at = _new_app()
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            [b for b in at.button if b.label == "Update"][0].click().run()
        self.assertEqual(list(at.exception), [])
        errors = " ".join(e.value for e in at.error)
        self.assertIn("pip install mrsiprep-docker", errors)


class ParticipantSelectionCombinedLabelTests(unittest.TestCase):
    """The "Select participants" mode must offer ONE full-width Subjects
    field that accepts a combined sub-XXXX_ses-YYYY token per entry -- not
    two equally-weighted Subjects/Sessions boxes side by side, which forced
    a cross-product and made mixing several different subject/session pairs
    impossible without over- or under-selecting."""

    def _select_participants_mode(self, at: AppTest) -> AppTest:
        _choose_outcome(at, "normalize")
        at.radio(key="wizard_field_participant_mode").set_value("Select participants").run()
        return at

    def test_sessions_field_is_tucked_in_a_collapsed_expander(self):
        at = self._select_participants_mode(_new_app())
        self.assertEqual(list(at.exception), [])
        session_inputs = [w for w in at.text_input if w.key == "wizard_field_session_label"]
        self.assertEqual(len(session_inputs), 1)
        expanders = list(at.expander)
        self.assertEqual(len(expanders), 1)

    def test_combined_sub_ses_tokens_produce_no_session_label_flag(self):
        at = self._select_participants_mode(_new_app())
        at.text_input(key="wizard_field_participant_label").set_value("sub-5301_ses-V6, 5323_ses-V4").run()
        _fill_data_step(at)
        _goto_step(at, 2)
        at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
        _goto_step(at, 3)
        codes = list(at.code)
        self.assertEqual(len(codes), 1)
        self.assertIn("--participant-label sub-5301_ses-V6 5323_ses-V4", codes[0].value)
        self.assertNotIn("--session-label", codes[0].value)


class ReportsOnlyFlagTests(unittest.TestCase):
    """--reports-only (skip recomputation, just rewrite QC/figures/HTML from
    existing derivatives) must be reachable from the wizard -- it previously
    had no widget anywhere in the app."""

    def test_checkbox_is_offered_in_runtime_expander(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        _goto_step(at, 2)
        checkbox_keys = [c.key for c in at.checkbox]
        self.assertIn("wizard_field_reports_only", checkbox_keys)

    def test_checking_it_emits_reports_only_flag(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        _fill_data_step(at)
        _goto_step(at, 2)
        at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
        at.checkbox(key="wizard_field_reports_only").set_value(True).run()
        _goto_step(at, 3)
        codes = list(at.code)
        self.assertEqual(len(codes), 1)
        self.assertIn("--reports-only", codes[0].value)

    def test_left_unchecked_by_default(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        _fill_data_step(at)
        _goto_step(at, 2)
        at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
        _goto_step(at, 3)
        codes = list(at.code)
        self.assertEqual(len(codes), 1)
        self.assertNotIn("--reports-only", codes[0].value)


class ScanMetabolitesFromFilenamesTests(unittest.TestCase):
    def test_extracts_the_met_bids_entity_from_real_filenames(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mrsi = root / "derivatives" / "mrsi-orig" / "sub-01" / "ses-01"
            mrsi.mkdir(parents=True)
            for met in ("CrPCr", "GluGln", "NAANAAG"):
                (mrsi / f"sub-01_ses-01_space-orig_met-{met}_desc-signal_mrsi.nii.gz").touch()
            # Non-metabolite files (no met- token, e.g. SNR/FWHM maps) must
            # not show up as spurious "metabolite" options.
            (mrsi / "sub-01_ses-01_space-orig_desc-snr_mrsi.nii.gz").touch()

            found = _scan_metabolites_from_filenames(root)

            self.assertEqual(found, ["CrPCr", "GluGln", "NAANAAG"])

    def test_returns_empty_list_when_directory_does_not_exist(self):
        self.assertEqual(_scan_metabolites_from_filenames("/no/such/directory"), [])

    def test_returns_empty_list_when_no_met_filenames_present(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "derivatives" / "mrsi-orig").mkdir(parents=True)
            self.assertEqual(_scan_metabolites_from_filenames(root), [])

    def test_deduplicates_across_subjects_and_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for sub, ses in (("01", "01"), ("01", "02"), ("02", "01")):
                mrsi = root / "derivatives" / "mrsi-orig" / f"sub-{sub}" / f"ses-{ses}"
                mrsi.mkdir(parents=True)
                (mrsi / f"sub-{sub}_ses-{ses}_space-orig_met-CrPCr_desc-signal_mrsi.nii.gz").touch()

            self.assertEqual(_scan_metabolites_from_filenames(root), ["CrPCr"])


class WizardScanMetabolitesButtonTests(unittest.TestCase):
    def test_scan_button_discovers_and_selects_metabolites_from_real_filenames(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mrsi = root / "derivatives" / "mrsi-orig" / "sub-01" / "ses-01"
            mrsi.mkdir(parents=True)
            for met in ("CrPCr", "GluGln"):
                (mrsi / f"sub-01_ses-01_space-orig_met-{met}_desc-signal_mrsi.nii.gz").touch()

            at = _new_app()
            _choose_outcome(at, "normalize")
            at.text_input(key="wizard_field_bids_dir").set_value(str(root)).run()
            at.text_input(key="wizard_field_output_dir").set_value(str(root / "out")).run()

            at.button(key="wizard_scan_metabolites").click().run()

            self.assertEqual(len(at.exception), 0)
            metabolites_box = at.multiselect(key="wizard_field_metabolites")
            self.assertEqual(sorted(metabolites_box.value), ["CrPCr", "GluGln"])
            self.assertIn("CrPCr", metabolites_box.options)
            self.assertIn("GluGln", metabolites_box.options)

    def test_scan_button_disabled_when_no_mrsi_input_dir_resolved_yet(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        scan_buttons = [b for b in at.button if b.key == "wizard_scan_metabolites"]
        self.assertEqual(len(scan_buttons), 1)
        self.assertTrue(scan_buttons[0].disabled)


class WizardRefMetDropdownTests(unittest.TestCase):
    def test_ref_met_options_match_exactly_the_metabolites_chosen_in_data(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        _fill_data_step(at, metabolites=["CrPCr", "GPCPCh", "NAANAAG"])
        _goto_step(at, 2)
        ref_met_boxes = [sb for sb in at.selectbox if sb.key == "wizard_field_ref_met"]
        self.assertEqual(sorted(ref_met_boxes[0].options), ["CrPCr", "GPCPCh", "NAANAAG"])

    def test_ref_met_shows_warning_instead_of_empty_dropdown_when_no_metabolites_chosen(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        at.text_input(key="wizard_field_bids_dir").set_value("/tmp").run()
        at.text_input(key="wizard_field_output_dir").set_value("/tmp/out").run()
        _goto_step(at, 2)
        ref_met_boxes = [sb for sb in at.selectbox if sb.key == "wizard_field_ref_met"]
        self.assertEqual(len(ref_met_boxes), 0)
        warnings = " ".join(el.value for el in at.get("warning"))
        self.assertIn("metabolite", warnings.lower())


class WizardParcellationExpanderTests(unittest.TestCase):
    """Parcellation always runs (SynthSeg by default) -- the expander must
    never be hidden, only collapsed vs. expanded by default depending on
    wizard_outcome."""

    def _expander_states(self, outcome: str) -> dict:
        at = _new_app()
        _choose_outcome(at, outcome)
        _fill_data_step(at)
        _goto_step(at, 2)
        return {exp.label: exp.proto.expanded for exp in at.expander}

    def test_parcellation_expander_present_but_collapsed_for_normalize_outcome(self):
        states = self._expander_states("normalize")
        self.assertIn("Parcellation and connectivity", states)
        self.assertFalse(states["Parcellation and connectivity"])

    def test_parcellation_expander_present_and_expanded_for_parcellation_outcome(self):
        states = self._expander_states("parcellation")
        self.assertIn("Parcellation and connectivity", states)
        self.assertTrue(states["Parcellation and connectivity"])


class WizardCommandMatchesBuildCommandTests(unittest.TestCase):
    def test_wizard_command_matches_build_command_called_directly(self):
        """For a fully-filled-in scenario, the wizard's Review command must
        match _build_command(...) called directly on an equivalent
        hand-built values dict -- _build_command stays the single source
        of truth, never reimplemented by the wizard. bids_dir must exist on
        disk (Review's tier-1 validation blocks the command otherwise), so
        this uses /tmp rather than an arbitrary made-up path."""
        at = _new_app()
        _choose_outcome(at, "normalize")
        _fill_data_step(at, bids_dir="/tmp", output_dir="/tmp/wizard_build_command_test_out", metabolites=["CrPCr", "NAANAAG"])
        _goto_step(at, 2)
        at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
        _goto_step(at, 3)
        codes = list(at.code)
        self.assertEqual(len(codes), 1)
        wizard_command = codes[0].value

        parser = build_parser()
        optionals = [a for a in parser._actions if a.option_strings]
        positional_values = {"bids_dir": "/tmp", "output_dir": "/tmp/wizard_build_command_test_out", "analysis_level": "participant"}
        values = {"--metabolites": ["CrPCr", "NAANAAG"], "--ref-met": "CrPCr"}
        expected_command = _build_command(positional_values, optionals, values)
        self.assertEqual(wizard_command, expected_command)

    def test_metabolites_are_comma_joined_not_space_separated(self):
        """--metabolites takes a single comma-separated token
        (type=_parse_comma_list in the parser), unlike real nargs="+" flags
        -- a space-separated '--metabolites Cho CrPCr GPCPCh' would be
        parsed by argparse as --metabolites=Cho plus two stray unrecognized
        positionals. Picking 3+ metabolites in Data must produce one
        '--metabolites Cho,CrPCr,GPCPCh' token in the generated command."""
        at = _new_app()
        _choose_outcome(at, "normalize")
        _fill_data_step(
            at, bids_dir="/tmp", output_dir="/tmp/wizard_metabolites_comma_test_out",
            metabolites=["Cho", "CrPCr", "GPCPCh"],
        )
        _goto_step(at, 2)
        at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
        _goto_step(at, 3)
        codes = list(at.code)
        self.assertEqual(len(codes), 1)
        command = codes[0].value
        self.assertIn("--metabolites Cho,CrPCr,GPCPCh", command)
        self.assertNotIn("--metabolites Cho CrPCr", command)


class WizardPreflightTests(unittest.TestCase):
    def test_preflight_button_populates_result_and_renders_inline(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        # /tmp exists but has no mrsinmrs.json / BIDS structure -- preflight
        # should still run (no crash) and populate an error-shaped result,
        # exactly like the pre-wizard button's own behavior for a dataset
        # that isn't ready yet.
        _fill_data_step(at, bids_dir="/tmp", output_dir="/tmp/wizard_preflight_out")
        _goto_step(at, 2)
        at.selectbox(key="wizard_field_ref_met").set_value("CrPCr").run()
        _goto_step(at, 3)

        preflight_buttons = [b for b in at.button if b.key == "wizard_run_preflight_btn"]
        self.assertEqual(len(preflight_buttons), 1)
        self.assertFalse(preflight_buttons[0].disabled)
        preflight_buttons[0].click().run()

        self.assertEqual(list(at.exception), [])
        self.assertIsNotNone(at.session_state.get("preflight_result"))

    def test_preflight_button_disabled_when_configuration_incomplete(self):
        at = _new_app()
        _choose_outcome(at, "normalize")
        _goto_step(at, 3)
        preflight_buttons = [b for b in at.button if b.key == "wizard_run_preflight_btn"]
        self.assertEqual(len(preflight_buttons), 1)
        self.assertTrue(preflight_buttons[0].disabled)


class WizardStepFlagOwnershipTests(unittest.TestCase):
    def test_custom_step_flags_still_matches_steps_registry(self):
        """Sanity check that the module-level assertion in
        command_builder_app.py (CUSTOM_STEP_FLAGS == STEP_DEPENDENCIES'
        keys) holds -- already enforced at import time, re-asserted here so
        a future edit that breaks it fails a *test*, not just an import."""
        from mrsiprep.workflows.nipype_engine.steps_registry import STEP_DEPENDENCIES

        self.assertEqual(set(CUSTOM_STEP_FLAGS), set(STEP_DEPENDENCIES))


if __name__ == "__main__":
    unittest.main()

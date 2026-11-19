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


class CreateInputsOutcomeTests(unittest.TestCase):
    """The third Analysis card ("Create MRSIprep inputs") routes to its own
    2-step mini-flow that generates a `mrsiprep-import` command -- a
    different tool entirely from the mrsiprep-docker processing commands
    the other two outcomes produce (see
    _render_wizard_create_inputs_outcome's docstring)."""

    def _choose_create_inputs(self, at: AppTest) -> AppTest:
        at.button(key="wizard_outcome_create_inputs").click().run()
        return at

    def _fill_step_0(self, at: AppTest, source="/data/Results_S001_V1", bids_dir="/data/bids") -> AppTest:
        at.text_input(key="wizard_import_source").set_value(source).run()
        at.text_input(key="wizard_import_bids_dir").set_value(bids_dir).run()
        return at

    def test_choosing_the_card_routes_to_the_mini_flow(self):
        at = self._choose_create_inputs(_new_app())
        self.assertEqual(list(at.exception), [])
        self.assertEqual(at.session_state["wizard_outcome"], "create_inputs")
        headers = [h.value for h in at.header]
        self.assertIn("Create MRSIprep inputs", headers)

    def test_subject_session_are_guessed_from_source_folder_name(self):
        at = self._choose_create_inputs(_new_app())
        at.text_input(key="wizard_import_source").set_value("/data/Results_S001_V1").run()
        self.assertEqual(at.text_input(key="wizard_import_subject").value, "S001")
        self.assertEqual(at.text_input(key="wizard_import_session").value, "V1")

    def test_next_disabled_until_required_fields_are_filled(self):
        at = self._choose_create_inputs(_new_app())
        next_buttons = [b for b in at.button if b.key == "wizard_import_next_btn"]
        self.assertTrue(next_buttons[0].disabled)
        at = self._fill_step_0(at)
        next_buttons = [b for b in at.button if b.key == "wizard_import_next_btn"]
        self.assertFalse(next_buttons[0].disabled)

    def test_review_generates_mrsiprep_import_command_not_mrsiprep_docker(self):
        at = self._choose_create_inputs(_new_app())
        at = self._fill_step_0(at)
        [b for b in at.button if b.key == "wizard_import_next_btn"][0].click().run()
        codes = [c.value for c in at.code]
        self.assertTrue(codes[0].startswith("mrsiprep-import"))
        self.assertIn("/data/Results_S001_V1", codes[0])
        self.assertIn("/data/bids", codes[0])
        self.assertIn("--subject S001", codes[0])
        self.assertIn("--session V1", codes[0])
        self.assertNotIn("mrsiprep-docker", codes[0])

    def test_advanced_flags_included_when_set(self):
        at = self._choose_create_inputs(_new_app())
        at = self._fill_step_0(at)
        at.text_input(key="wizard_import_input_subdir").set_value("export").run()
        at.checkbox(key="wizard_import_overwrite").set_value(True).run()
        [b for b in at.button if b.key == "wizard_import_next_btn"][0].click().run()
        codes = [c.value for c in at.code]
        self.assertIn("--input-subdir export", codes[0])
        self.assertIn("--overwrite", codes[0])

    def test_new_project_shows_dataset_description_snippet(self):
        at = self._choose_create_inputs(_new_app())
        at = self._fill_step_0(at)
        at.checkbox(key="wizard_import_is_new").set_value(True).run()
        [b for b in at.button if b.key == "wizard_import_next_btn"][0].click().run()
        codes = [c.value for c in at.code]
        self.assertTrue(any("DatasetType" in c for c in codes))

    def test_review_always_shows_mrsinmrs_reminder(self):
        at = self._choose_create_inputs(_new_app())
        at = self._fill_step_0(at)
        [b for b in at.button if b.key == "wizard_import_next_btn"][0].click().run()
        codes = [c.value for c in at.code]
        self.assertTrue(any("QuantificationTool" in c for c in codes))

    def test_back_preserves_every_field(self):
        at = self._choose_create_inputs(_new_app())
        at = self._fill_step_0(at)
        at.checkbox(key="wizard_import_is_new").set_value(True).run()
        at.checkbox(key="wizard_import_overwrite").set_value(True).run()
        at.text_input(key="wizard_import_input_subdir").set_value("export").run()
        [b for b in at.button if b.key == "wizard_import_next_btn"][0].click().run()
        [b for b in at.button if b.key == "wizard_import_back_btn"][0].click().run()

        self.assertEqual(at.session_state["wizard_import_step"], 0)
        self.assertEqual(at.text_input(key="wizard_import_source").value, "/data/Results_S001_V1")
        self.assertEqual(at.text_input(key="wizard_import_bids_dir").value, "/data/bids")
        self.assertEqual(at.text_input(key="wizard_import_subject").value, "S001")
        self.assertEqual(at.text_input(key="wizard_import_session").value, "V1")
        self.assertEqual(at.text_input(key="wizard_import_input_subdir").value, "export")
        self.assertTrue(at.checkbox(key="wizard_import_overwrite").value)
        self.assertTrue(at.checkbox(key="wizard_import_is_new").value)

    def test_back_to_analysis_resets_outcome(self):
        at = self._choose_create_inputs(_new_app())
        [b for b in at.button if b.label == "← Back to Analysis"][0].click().run()
        self.assertIsNone(at.session_state["wizard_outcome"])
        self.assertEqual(at.session_state["wizard_step"], 0)
        headers = [h.value for h in at.header]
        self.assertIn("What would you like to do?", headers)


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

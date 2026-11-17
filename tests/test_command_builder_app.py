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

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from mrsiprep.interfaces.command_builder_app import (
    CUSTOM_STEP_FLAGS,
    _build_command,
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

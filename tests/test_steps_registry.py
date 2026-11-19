import unittest
from types import SimpleNamespace

from mrsiprep.workflows.nipype_engine.nodes import STEP_SEQUENCE
from mrsiprep.workflows.nipype_engine.steps_registry import (
    STEP_DEPENDENCIES,
    resolve_step_order,
    terminal_node,
    validate_step_order,
)


class StepDependenciesRegistryTests(unittest.TestCase):
    def test_every_step_sequence_entry_has_exactly_one_registry_entry(self):
        self.assertEqual(set(STEP_DEPENDENCIES), {name for name, _ in STEP_SEQUENCE})

    def test_mrsi_quality_requires_mrsi_load(self):
        # mrsi_quality reads this recording's resolved MRSinMRS metadata
        # (field strength, for linewidth-unit conversion) off
        # ctx["mrsi_load"].mrsinmrs_resolved -- a real ctx dependency, not
        # just an ordering nicety.
        self.assertIn("mrsi_load", STEP_DEPENDENCIES["mrsi_quality"].requires)


class ValidateStepOrderTests(unittest.TestCase):
    def test_unknown_step_name_raises_naming_it(self):
        with self.assertRaisesRegex(ValueError, "not_a_real_step"):
            validate_step_order(["prepare", "not_a_real_step"])

    def test_old_pre_split_step_names_are_rejected(self):
        # "anat"/"mrsi" were renamed/split to anatprep/mrsi_load+
        # t1_saturation_correction+mrsi_reference+mrsi_quality -- a hard
        # break, no aliasing.
        with self.assertRaisesRegex(ValueError, "'anat'"):
            validate_step_order(["prepare", "anat"])
        with self.assertRaisesRegex(ValueError, "'mrsi'"):
            validate_step_order(["prepare", "mrsi"])

    def test_old_pre_split_mrsi_finish_name_is_rejected(self):
        # "mrsi_finish" was split into mrsi_reference (reference-metabolite
        # image) and mrsi_quality (voxel-quality masks) -- neither call
        # depended on the other's output, and most downstream steps only
        # ever needed one of the two -- a hard break, no aliasing.
        with self.assertRaisesRegex(ValueError, "'mrsi_finish'"):
            validate_step_order(["prepare", "mrsi_finish"])

    def test_old_pre_rename_parcellation_names_are_rejected(self):
        # "synthseg_parc_qc"/"parcellation" were renamed to
        # anat_parcellation_qc/mrsi_parcellation -- a hard break, no aliasing.
        with self.assertRaisesRegex(ValueError, "'synthseg_parc_qc'"):
            validate_step_order(["prepare", "synthseg_parc_qc"])
        with self.assertRaisesRegex(ValueError, "'parcellation'"):
            validate_step_order(["prepare", "parcellation"])

    def test_old_pre_rename_t1_water_correction_name_is_rejected(self):
        # "t1_water_correction" was renamed to t1_saturation_correction --
        # the step corrects the metabolite's own T1 saturation, not water's
        # T1, and never touches water-reference data -- a hard break, no
        # aliasing.
        with self.assertRaisesRegex(ValueError, "'t1_water_correction'"):
            validate_step_order(["prepare", "t1_water_correction"])

    def test_missing_dependency_raises_naming_step_and_missing_key(self):
        # mrsi_parcellation needs registration's/anat_parcellation_qc's
        # output, neither listed.
        with self.assertRaisesRegex(ValueError, r"'mrsi_parcellation'.*registration"):
            validate_step_order(
                [
                    "prepare", "tissue_seg", "anatprep", "mrsi_load", "spike_filter", "t1_saturation_correction",
                    "mrsi_reference", "mrsi_quality", "mrsi_parcellation",
                ]
            )

    def test_omitting_a_step_whose_output_nothing_downstream_needs_succeeds(self):
        # tissue_qc's own output (qc_sections_tissue) is never required by anything.
        validate_step_order(
            [
                "prepare", "tissue_seg", "anatprep", "mrsi_load", "spike_filter", "t1_saturation_correction",
                "mrsi_reference", "mrsi_quality", "registration", "tissue_probmaps",
            ]
        )

    def test_omitting_a_depended_on_step_hard_fails(self):
        # anatprep's output is required by registration.
        with self.assertRaisesRegex(ValueError, "'registration'"):
            validate_step_order(
                [
                    "prepare", "tissue_seg", "mrsi_load", "spike_filter", "t1_saturation_correction",
                    "mrsi_reference", "mrsi_quality", "registration",
                ]
            )

    def test_mrsi_reference_without_t1_saturation_correction_hard_fails(self):
        with self.assertRaisesRegex(ValueError, "'mrsi_reference'.*t1_saturation_correction"):
            validate_step_order(["prepare", "mrsi_load", "spike_filter", "mrsi_reference"])

    def test_mrsi_quality_without_mrsi_reference_hard_fails(self):
        with self.assertRaisesRegex(ValueError, "'mrsi_quality'.*mrsi_reference"):
            validate_step_order(["prepare", "mrsi_load", "spike_filter", "t1_saturation_correction", "mrsi_quality"])

    def test_t1_saturation_correction_without_spike_filter_hard_fails(self):
        with self.assertRaisesRegex(ValueError, "'t1_saturation_correction'.*spike_filter"):
            validate_step_order(["prepare", "mrsi_load", "t1_saturation_correction"])

    def test_full_default_order_validates_cleanly(self):
        validate_step_order([name for name, _ in STEP_SEQUENCE])

    def test_optional_dependency_never_blocks(self):
        # mrsi_load's `anatprep` dependency is optional; mrsi_load before anatprep is legal.
        validate_step_order(["prepare", "mrsi_load"])


class ResolveStepOrderTests(unittest.TestCase):
    def test_omitted_steps_matches_default_sequence_exactly(self):
        cfg = SimpleNamespace(steps=None)
        self.assertIs(resolve_step_order(cfg), STEP_SEQUENCE)

    def test_custom_order_resolves_requested_names_and_callables(self):
        by_name = dict(STEP_SEQUENCE)
        cfg = SimpleNamespace(steps=["prepare", "tissue_seg", "anatprep"])
        resolved = resolve_step_order(cfg)
        self.assertEqual([name for name, _ in resolved], ["prepare", "tissue_seg", "anatprep"])
        self.assertIs(resolved[0][1], by_name["prepare"])
        self.assertIs(resolved[-1][1], by_name["anatprep"])


class TerminalNodeTests(unittest.TestCase):
    def test_default_terminal_node_is_reports(self):
        self.assertEqual(terminal_node(SimpleNamespace(steps=None)), "reports")

    def test_custom_subset_terminal_node_is_its_last_requested_step(self):
        self.assertEqual(terminal_node(SimpleNamespace(steps=["prepare", "tissue_seg", "anatprep"])), "anatprep")


if __name__ == "__main__":
    unittest.main()

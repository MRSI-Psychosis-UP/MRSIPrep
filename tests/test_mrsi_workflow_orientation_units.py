import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.io.loaders import MRSIInputs
from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.workflows.mrsi import _derivative_map_paths, run_mrsi_workflow


def _config(**overrides):
    base = dict(
        derivative_dir=Path("/out"),
        overwrite=False,
        ref_met="CrPCr",
        correct_mrsi_orientation=False,
        t1_correction="none",
        registration_backend="ants",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _inputs():
    return MRSIInputs(metabolite_maps={"CrPCr": Path("cr.nii.gz")}, crlb_maps={}, brainmask=Path("mask.nii.gz"))


class DerivativeMapPathsTests(unittest.TestCase):
    def test_matches_the_paths_copy_native_maps_writes_to(self):
        config = _config()
        inputs = MRSIInputs(
            metabolite_maps={"CrPCr": Path("in-cr.nii.gz")},
            crlb_maps={"CrPCr": Path("in-crlb.nii.gz")},
            snr_map=Path("in-snr.nii.gz"),
            linewidth_map=Path("in-fwhm.nii.gz"),
            water_map=Path("in-water.nii.gz"),
        )

        metabolite_maps, crlb_maps, snr_map, linewidth_map, water_map = _derivative_map_paths(config, "S001", "V1", inputs)

        self.assertEqual(
            metabolite_maps["CrPCr"],
            mrsi_derivative(config.derivative_dir, "S001", "V1", space="mrsi", met="CrPCr", desc="signal", suffix_override="mrsi"),
        )
        self.assertEqual(
            crlb_maps["CrPCr"],
            mrsi_derivative(config.derivative_dir, "S001", "V1", space="orig", met="CrPCr", desc="crlb", suffix_override="mrsi"),
        )
        self.assertEqual(
            snr_map, mrsi_derivative(config.derivative_dir, "S001", "V1", space="orig", desc="snr", suffix_override="mrsi")
        )
        self.assertEqual(
            linewidth_map, mrsi_derivative(config.derivative_dir, "S001", "V1", space="orig", desc="fwhm", suffix_override="mrsi")
        )
        self.assertEqual(
            water_map,
            mrsi_derivative(config.derivative_dir, "S001", "V1", space="mrsi", met="water", desc="signal", suffix_override="mrsi"),
        )

    def test_omits_snr_linewidth_and_water_when_not_provided(self):
        config = _config()
        inputs = MRSIInputs(metabolite_maps={"CrPCr": Path("in-cr.nii.gz")})

        _metabolite_maps, _crlb_maps, snr_map, linewidth_map, water_map = _derivative_map_paths(config, "S001", "V1", inputs)

        self.assertIsNone(snr_map)
        self.assertIsNone(linewidth_map)
        self.assertIsNone(water_map)


class RunMrsiWorkflowOrientationTests(unittest.TestCase):
    def _patches(self):
        return [
            patch("mrsiprep.workflows.mrsi._copy_native_maps"),
            patch("mrsiprep.workflows.mrsi.ensure_brainmask", return_value=Path("mask.nii.gz")),
            patch("mrsiprep.workflows.mrsi.filter_metabolite_maps", return_value={"CrPCr": Path("cr.nii.gz")}),
            patch("mrsiprep.workflows.mrsi.generate_reference", return_value=Path("ref.nii.gz")),
            patch("mrsiprep.workflows.mrsi.make_quality_masks", return_value=({}, Path("qc.tsv"))),
        ]

    def test_orientation_correction_is_skipped_by_default(self):
        patches = self._patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
            "mrsiprep.workflows.mrsi.correct_mrsi_orientation"
        ) as correct:
            run_mrsi_workflow(_config(), "S001", "V1", _inputs(), t1_path=Path("t1.nii.gz"))
        correct.assert_not_called()

    def test_orientation_correction_runs_first_when_enabled_against_derivative_paths(self):
        # correct_mrsi_orientation must never see inputs.metabolite_maps
        # directly -- those are input BIDS paths, commonly mounted
        # read-only, not the writable derivatives copies this run owns.
        derivative_paths = ({"CrPCr": Path("/out/derivatives/mrsi/orig/cr.nii.gz")}, {}, None, None, None)
        patches = self._patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
            "mrsiprep.workflows.mrsi._derivative_map_paths", return_value=derivative_paths
        ), patch("mrsiprep.workflows.mrsi.correct_mrsi_orientation") as correct:
            run_mrsi_workflow(_config(correct_mrsi_orientation=True), "S001", "V1", _inputs(), t1_path=Path("t1.nii.gz"))
        correct.assert_called_once()
        self.assertEqual(correct.call_args.args[3], derivative_paths[0])
        self.assertEqual(correct.call_args.args[4], Path("t1.nii.gz"))
        self.assertNotIn("brainmask", correct.call_args.kwargs)

    def test_inputs_are_reassigned_to_the_corrected_derivative_paths(self):
        # Regression guard: correction rewrote maps in place under new
        # derivative paths, but ensure_brainmask/filter_metabolite_maps
        # right after it were still reading inputs.metabolite_maps -- the
        # original (uncorrected, possibly read-only) paths -- unless inputs
        # itself gets updated to point at the corrected copies too.
        derivative_maps = {"CrPCr": Path("/out/derivatives/mrsi/orig/cr-corrected.nii.gz")}
        derivative_water = Path("/out/derivatives/mrsi/orig/water-corrected.nii.gz")
        derivative_paths = (derivative_maps, {}, None, None, derivative_water)
        patches = self._patches()
        with patches[0], patches[1] as ensure_brainmask, patches[2] as filter_maps, patches[3], patches[4], patch(
            "mrsiprep.workflows.mrsi._derivative_map_paths", return_value=derivative_paths
        ), patch("mrsiprep.workflows.mrsi.correct_mrsi_orientation"):
            run_mrsi_workflow(_config(correct_mrsi_orientation=True), "S001", "V1", _inputs(), t1_path=Path("t1.nii.gz"))
        self.assertEqual(ensure_brainmask.call_args.args[4], derivative_water)
        self.assertEqual(ensure_brainmask.call_args.args[5], derivative_maps)
        self.assertEqual(filter_maps.call_args.args[3], derivative_maps)

    def test_raises_a_clear_error_without_a_t1_path(self):
        patches = self._patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with self.assertRaisesRegex(ValueError, "--correct-mrsi-orientation"):
                run_mrsi_workflow(_config(correct_mrsi_orientation=True), "S001", "V1", _inputs(), t1_path=None)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.io.loaders import MRSIInputs
from mrsiprep.workflows.mrsi import run_mrsi_workflow


def _config(**overrides):
    base = dict(
        derivative_dir=Path("/out"),
        overwrite=False,
        ref_met="CrPCr",
        correct_mrsi_orientation=False,
        t1_correction="none",
        t1_correction_water_status="unknown",
        registration_backend="ants",
        mrsinmrs=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _inputs(**overrides):
    base = dict(metabolite_maps={"CrPCr": Path("cr.nii.gz")}, crlb_maps={}, brainmask=Path("mask.nii.gz"))
    base.update(overrides)
    return MRSIInputs(**base)


def _patches():
    return [
        patch("mrsiprep.workflows.mrsi._copy_native_maps"),
        patch("mrsiprep.workflows.mrsi.ensure_brainmask", return_value=Path("mask.nii.gz")),
        patch("mrsiprep.workflows.mrsi.filter_metabolite_maps", return_value={"CrPCr": Path("preproc-cr.nii.gz")}),
        patch("mrsiprep.workflows.mrsi.generate_reference", return_value=Path("ref.nii.gz")),
        patch("mrsiprep.workflows.mrsi.make_quality_masks", return_value=({}, Path("qc.tsv"))),
    ]


class RunMrsiWorkflowVoxelwiseT1CorrectionTests(unittest.TestCase):
    def test_raises_a_clear_error_without_a_flip_angle_map(self):
        patches = _patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with self.assertRaisesRegex(ValueError, "--t1-correction voxelwise requires"):
                run_mrsi_workflow(_config(t1_correction="voxelwise"), "S001", "V1", _inputs(flip_angle_map=None))

    def test_dispatches_to_voxelwise_correction_when_flip_angle_map_present(self):
        patches = _patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
            "mrsiprep.workflows.mrsi.resolve_mrsinmrs", return_value={"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0}
        ), patch("mrsiprep.workflows.mrsi.apply_t1_correction_voxelwise", return_value=({"CrPCr": Path("corrected.nii.gz")}, ["row"], Path("summary.tsv"))) as apply_voxelwise, patch(
            "mrsiprep.workflows.mrsi.apply_t1_correction"
        ) as apply_literature:
            result = run_mrsi_workflow(
                _config(t1_correction="voxelwise"), "S001", "V1", _inputs(flip_angle_map=Path("b1map.nii.gz"))
            )

        apply_voxelwise.assert_called_once()
        apply_literature.assert_not_called()
        self.assertEqual(apply_voxelwise.call_args.args[4], Path("b1map.nii.gz"))
        self.assertEqual(result.corrected_maps, {"CrPCr": Path("corrected.nii.gz")})
        self.assertEqual(result.t1_correction_provenance, ["row"])
        self.assertEqual(result.flip_angle_map, Path("b1map.nii.gz"))

    def test_literature_mode_does_not_require_a_flip_angle_map(self):
        patches = _patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
            "mrsiprep.workflows.mrsi.resolve_mrsinmrs", return_value={"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0}
        ), patch("mrsiprep.workflows.mrsi.apply_t1_correction", return_value=({"CrPCr": Path("corrected.nii.gz")}, ["row"], Path("summary.tsv"))) as apply_literature, patch(
            "mrsiprep.workflows.mrsi.apply_t1_correction_voxelwise"
        ) as apply_voxelwise:
            run_mrsi_workflow(_config(t1_correction="literature"), "S001", "V1", _inputs(flip_angle_map=None))

        apply_literature.assert_called_once()
        apply_voxelwise.assert_not_called()

    def test_none_mode_calls_neither_correction_function(self):
        patches = _patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
            "mrsiprep.workflows.mrsi.apply_t1_correction"
        ) as apply_literature, patch("mrsiprep.workflows.mrsi.apply_t1_correction_voxelwise") as apply_voxelwise:
            result = run_mrsi_workflow(_config(t1_correction="none"), "S001", "V1", _inputs())

        apply_literature.assert_not_called()
        apply_voxelwise.assert_not_called()
        self.assertIsNone(result.t1_correction_provenance)


if __name__ == "__main__":
    unittest.main()

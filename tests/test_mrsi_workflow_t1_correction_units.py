import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.workflows.mrsi import MRSILoadResult, SpikeFilterResult, run_t1_saturation_correction_workflow


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


def _load(**overrides):
    base = dict(
        raw_maps={"CrPCr": Path("raw-cr.nii.gz")},
        brainmask=Path("mask.nii.gz"),
        crlb_maps={},
        snr_map=None,
        linewidth_map=None,
        water_map=None,
        flip_angle_map=None,
        mrsinmrs_resolved=None,
    )
    base.update(overrides)
    return MRSILoadResult(**base)


def _filtered(**overrides):
    base = dict(preproc_maps={"CrPCr": Path("preproc-cr.nii.gz")})
    base.update(overrides)
    return SpikeFilterResult(**base)


class RunT1WaterCorrectionWorkflowVoxelwiseTests(unittest.TestCase):
    def test_raises_a_clear_error_without_a_flip_angle_map(self):
        with self.assertRaisesRegex(ValueError, "--t1-correction voxelwise requires"):
            run_t1_saturation_correction_workflow(
                _config(t1_correction="voxelwise"), "S001", "V1", _load(flip_angle_map=None), _filtered()
            )

    def test_dispatches_to_voxelwise_correction_when_flip_angle_map_present(self):
        mrsinmrs_resolved = {"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0}
        with patch(
            "mrsiprep.workflows.mrsi.apply_t1_correction_voxelwise", return_value=({"CrPCr": Path("corrected.nii.gz")}, ["row"], Path("summary.tsv"))
        ) as apply_voxelwise, patch("mrsiprep.workflows.mrsi.apply_t1_correction") as apply_literature:
            result = run_t1_saturation_correction_workflow(
                _config(t1_correction="voxelwise"), "S001", "V1",
                _load(flip_angle_map=Path("b1map.nii.gz"), mrsinmrs_resolved=mrsinmrs_resolved), _filtered(),
            )

        apply_voxelwise.assert_called_once()
        apply_literature.assert_not_called()
        self.assertEqual(apply_voxelwise.call_args.args[4], Path("b1map.nii.gz"))
        self.assertEqual(result.corrected_maps, {"CrPCr": Path("corrected.nii.gz")})
        self.assertEqual(result.provenance, ["row"])

    def test_literature_mode_does_not_require_a_flip_angle_map(self):
        mrsinmrs_resolved = {"RepetitionTime": 2.0, "FlipAngle": 90.0, "MagneticFieldStrength": 3.0}
        with patch(
            "mrsiprep.workflows.mrsi.apply_t1_correction", return_value=({"CrPCr": Path("corrected.nii.gz")}, ["row"], Path("summary.tsv"))
        ) as apply_literature, patch("mrsiprep.workflows.mrsi.apply_t1_correction_voxelwise") as apply_voxelwise:
            run_t1_saturation_correction_workflow(
                _config(t1_correction="literature"), "S001", "V1", _load(flip_angle_map=None, mrsinmrs_resolved=mrsinmrs_resolved), _filtered()
            )

        apply_literature.assert_called_once()
        apply_voxelwise.assert_not_called()

    def test_none_mode_calls_neither_correction_function_and_is_a_pure_passthrough(self):
        with patch("mrsiprep.workflows.mrsi.apply_t1_correction") as apply_literature, patch(
            "mrsiprep.workflows.mrsi.apply_t1_correction_voxelwise"
        ) as apply_voxelwise:
            load = _load()
            filtered = _filtered()
            result = run_t1_saturation_correction_workflow(_config(t1_correction="none"), "S001", "V1", load, filtered)

        apply_literature.assert_not_called()
        apply_voxelwise.assert_not_called()
        self.assertIsNone(result.provenance)
        # True no-op: the same object, not merely an equal copy.
        self.assertIs(result.corrected_maps, filtered.preproc_maps)


if __name__ == "__main__":
    unittest.main()

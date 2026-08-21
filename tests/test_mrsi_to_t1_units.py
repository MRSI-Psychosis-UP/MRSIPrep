import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.registration.mrsi_to_t1 import MRSIToT1Result, _voxel_size_mm, run_mrsi_to_t1

MODULE = "mrsiprep.registration.mrsi_to_t1"


def _config(root: Path, **overrides):
    base = dict(
        derivative_dir=root / "derivatives",
        registration_backend="ants",
        fsl_deformable=False,
        overwrite=False,
        overwrite_t1_reg=False,
        ants_mrsi_to_t1_transform="sr",
        fsl_mrsi_to_t1_dof=6,
        fsl_mrsi_to_t1_init="flirt",
        fsl_cost="corratio",
        fsl_fnirt_warpres=None,
        fsl_fnirt_lambda="300,200,150,150",
        nthreads=4,
        verbose=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class VoxelSizeTests(unittest.TestCase):
    def test_reads_the_first_three_zooms_as_floats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "img.nii.gz"
            img = nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.diag([5.0, 5.0, 5.2, 1.0]))
            nib.save(img, path)

            zooms = _voxel_size_mm(path)

            self.assertEqual(len(zooms), 3)
            self.assertAlmostEqual(zooms[0], 5.0, places=4)
            self.assertAlmostEqual(zooms[2], 5.2, places=4)
            for value in zooms:
                self.assertIsInstance(value, float)


class RunMrsiToT1BackendDispatchTests(unittest.TestCase):
    def _patches(self):
        return (
            patch(f"{MODULE}.register"),
            patch(f"{MODULE}.register_flirt"),
            patch(f"{MODULE}.register_fnirt"),
            patch(f"{MODULE}.all_exist", return_value=False),
            patch(f"{MODULE}.transform_paths", return_value=[Path("/x/xfm.mat")]),
            patch(f"{MODULE}.ants_transform_prefix", return_value=Path("/x/prefix")),
        )

    def test_ants_backend_calls_ants_register_with_the_configured_transform(self):
        ants, flirt, fnirt, exists, paths, prefix = self._patches()
        with tempfile.TemporaryDirectory() as tmpdir, ants as ants_mock, flirt as flirt_mock, fnirt as fnirt_mock, exists, paths, prefix:
            run_mrsi_to_t1(_config(Path(tmpdir)), "S001", "V1", "REF", "T1")

        ants_mock.assert_called_once()
        flirt_mock.assert_not_called()
        fnirt_mock.assert_not_called()
        self.assertEqual(ants_mock.call_args.kwargs["transform"], "sr")
        self.assertEqual(ants_mock.call_args.kwargs["threads"], 4)

    def test_ants_registers_mrsi_onto_t1_as_the_fixed_image(self):
        ants, flirt, fnirt, exists, paths, prefix = self._patches()
        with tempfile.TemporaryDirectory() as tmpdir, ants as ants_mock, flirt, fnirt, exists, paths, prefix:
            run_mrsi_to_t1(_config(Path(tmpdir)), "S001", "V1", "REF", "T1")

        # T1 is fixed, the MRSI reference is moving.
        self.assertEqual(ants_mock.call_args.args[0], "T1")
        self.assertEqual(ants_mock.call_args.args[1], "REF")

    def test_fsl_backend_without_deformable_uses_flirt_only(self):
        ants, flirt, fnirt, exists, paths, prefix = self._patches()
        with tempfile.TemporaryDirectory() as tmpdir, ants as ants_mock, flirt as flirt_mock, fnirt as fnirt_mock, exists, paths, prefix:
            run_mrsi_to_t1(
                _config(Path(tmpdir), registration_backend="fsl", fsl_deformable=False), "S001", "V1", "REF", "T1"
            )

        flirt_mock.assert_called_once()
        fnirt_mock.assert_not_called()
        ants_mock.assert_not_called()
        self.assertEqual(flirt_mock.call_args.kwargs["flirt_dof"], 6)
        self.assertEqual(flirt_mock.call_args.kwargs["flirt_init"], "flirt")

    def test_fsl_deformable_uses_fnirt(self):
        ants, flirt, fnirt, exists, paths, prefix = self._patches()
        with tempfile.TemporaryDirectory() as tmpdir, ants, flirt as flirt_mock, fnirt as fnirt_mock, exists, paths, prefix:
            run_mrsi_to_t1(
                # Explicit warpres so this stays a dispatch test -- the
                # None case would read voxel sizes off a real image.
                _config(
                    Path(tmpdir), registration_backend="fsl", fsl_deformable=True, fsl_fnirt_warpres=(6, 6, 6)
                ),
                "S001", "V1", "REF", "T1", moving_mask="MOVING",
            )

        fnirt_mock.assert_called_once()
        flirt_mock.assert_not_called()
        self.assertEqual(fnirt_mock.call_args.kwargs["moving_mask"], "MOVING")
        self.assertEqual(fnirt_mock.call_args.kwargs["lambda_weight"], "300,200,150,150")

    def test_fnirt_without_a_moving_mask_raises(self):
        ants, flirt, fnirt, exists, paths, prefix = self._patches()
        with tempfile.TemporaryDirectory() as tmpdir, ants, flirt, fnirt as fnirt_mock, exists, paths, prefix:
            with self.assertRaisesRegex(ValueError, "FNIRT.*requires an MRSI brainmask"):
                run_mrsi_to_t1(
                    _config(Path(tmpdir), registration_backend="fsl", fsl_deformable=True),
                    "S001", "V1", "REF", "T1", moving_mask=None,
                )

        fnirt_mock.assert_not_called()

    def test_deformable_flag_is_ignored_for_the_ants_backend(self):
        # fsl_deformable only means anything under the fsl backend.
        ants, flirt, fnirt, exists, paths, prefix = self._patches()
        with tempfile.TemporaryDirectory() as tmpdir, ants as ants_mock, flirt, fnirt as fnirt_mock, exists, paths, prefix:
            run_mrsi_to_t1(
                _config(Path(tmpdir), registration_backend="ants", fsl_deformable=True), "S001", "V1", "REF", "T1"
            )

        ants_mock.assert_called_once()
        fnirt_mock.assert_not_called()

    def test_explicit_warpres_overrides_the_voxel_derived_default(self):
        ants, flirt, fnirt, exists, paths, prefix = self._patches()
        with tempfile.TemporaryDirectory() as tmpdir, ants, flirt, fnirt as fnirt_mock, exists, paths, prefix, patch(
            f"{MODULE}.default_fnirt_warpres"
        ) as default_mock:
            run_mrsi_to_t1(
                _config(Path(tmpdir), registration_backend="fsl", fsl_deformable=True, fsl_fnirt_warpres=(6, 6, 6)),
                "S001", "V1", "REF", "T1", moving_mask="MOVING",
            )

        default_mock.assert_not_called()
        self.assertEqual(fnirt_mock.call_args.kwargs["warpres"], (6, 6, 6))

    def test_absent_warpres_falls_back_to_the_voxel_size_default(self):
        ants, flirt, fnirt, exists, paths, prefix = self._patches()
        with tempfile.TemporaryDirectory() as tmpdir, ants, flirt, fnirt as fnirt_mock, exists, paths, prefix, patch(
            f"{MODULE}.default_fnirt_warpres", return_value=(10, 10, 10)
        ) as default_mock, patch(f"{MODULE}._voxel_size_mm", return_value=(5.0, 5.0, 5.2)):
            run_mrsi_to_t1(
                _config(Path(tmpdir), registration_backend="fsl", fsl_deformable=True, fsl_fnirt_warpres=None),
                "S001", "V1", "REF", "T1", moving_mask="MOVING",
            )

        default_mock.assert_called_once_with((5.0, 5.0, 5.2))
        self.assertEqual(fnirt_mock.call_args.kwargs["warpres"], (10, 10, 10))

    def test_verbose_is_gated_at_level_three(self):
        ants, flirt, fnirt, exists, paths, prefix = self._patches()
        for verbose, expected in ((2, False), (3, True)):
            ants, flirt, fnirt, exists, paths, prefix = self._patches()
            with tempfile.TemporaryDirectory() as tmpdir, ants as ants_mock, flirt, fnirt, exists, paths, prefix:
                run_mrsi_to_t1(_config(Path(tmpdir), verbose=verbose), "S001", "V1", "REF", "T1")
            self.assertEqual(ants_mock.call_args.kwargs["verbose"], expected, msg=f"verbose={verbose}")


class RunMrsiToT1CacheTests(unittest.TestCase):
    def _patches(self, all_exist_value):
        return (
            patch(f"{MODULE}.register"),
            patch(f"{MODULE}.all_exist", return_value=all_exist_value),
            patch(f"{MODULE}.transform_paths", return_value=[Path("/x/xfm.mat")]),
            patch(f"{MODULE}.ants_transform_prefix", return_value=Path("/x/prefix")),
        )

    def test_existing_transforms_short_circuit_registration(self):
        ants, exists, paths, prefix = self._patches(True)
        with tempfile.TemporaryDirectory() as tmpdir, ants as ants_mock, exists, paths, prefix:
            result = run_mrsi_to_t1(_config(Path(tmpdir)), "S001", "V1", "REF", "T1")

        ants_mock.assert_not_called()
        self.assertIsInstance(result, MRSIToT1Result)

    def test_overwrite_t1_reg_forces_reregistration(self):
        ants, exists, paths, prefix = self._patches(True)
        with tempfile.TemporaryDirectory() as tmpdir, ants as ants_mock, exists, paths, prefix:
            run_mrsi_to_t1(_config(Path(tmpdir), overwrite_t1_reg=True), "S001", "V1", "REF", "T1")

        ants_mock.assert_called_once()

    def test_global_overwrite_forces_reregistration(self):
        ants, exists, paths, prefix = self._patches(True)
        with tempfile.TemporaryDirectory() as tmpdir, ants as ants_mock, exists, paths, prefix:
            run_mrsi_to_t1(_config(Path(tmpdir), overwrite=True), "S001", "V1", "REF", "T1")

        ants_mock.assert_called_once()

    def test_result_carries_forward_inverse_and_prefix(self):
        ants, exists, paths, prefix = self._patches(False)
        with tempfile.TemporaryDirectory() as tmpdir, ants, exists, paths, prefix:
            result = run_mrsi_to_t1(_config(Path(tmpdir)), "S001", "V1", "REF", "T1")

        self.assertEqual(result.forward, [Path("/x/xfm.mat")])
        self.assertEqual(result.inverse, [Path("/x/xfm.mat")])
        self.assertEqual(result.prefix, Path("/x/prefix"))

    def test_post_registration_paths_exclude_missing_transforms(self):
        # After registering, only files that actually materialized are
        # reported -- unlike the pre-flight probe, which lists expected paths.
        with tempfile.TemporaryDirectory() as tmpdir, patch(f"{MODULE}.register"), patch(
            f"{MODULE}.all_exist", return_value=False
        ), patch(f"{MODULE}.transform_paths", return_value=[Path("/x/xfm.mat")]) as paths_mock, patch(
            f"{MODULE}.ants_transform_prefix", return_value=Path("/x/prefix")
        ):
            run_mrsi_to_t1(_config(Path(tmpdir)), "S001", "V1", "REF", "T1")

        include_missing = [c.kwargs.get("include_missing") for c in paths_mock.call_args_list]
        self.assertIn(False, include_missing)


if __name__ == "__main__":
    unittest.main()

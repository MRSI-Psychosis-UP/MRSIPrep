import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mrsiprep.interfaces.fsl import (
    FSLError,
    _apply_affine,
    _apply_warp,
    _applywarp_interpolation,
    _flirt_interpolation,
    _invert_affine,
    _regrid_mask_onto,
    register_flirt,
    register_fnirt,
    require_cli,
    run_fast,
)


class RequireCliTests(unittest.TestCase):
    def test_raises_when_not_on_path(self):
        with patch("mrsiprep.interfaces.fsl.shutil.which", return_value=None):
            with self.assertRaisesRegex(FSLError, "flirt"):
                require_cli("flirt")

    def test_returns_resolved_path(self):
        with patch("mrsiprep.interfaces.fsl.shutil.which", return_value="/usr/local/fsl/bin/flirt"):
            self.assertEqual(require_cli("flirt"), "/usr/local/fsl/bin/flirt")


class InterpolationMappingTests(unittest.TestCase):
    def test_flirt_interpolation_known_names(self):
        self.assertEqual(_flirt_interpolation("linear"), "trilinear")
        self.assertEqual(_flirt_interpolation("nearestNeighbor"), "nearestneighbour")
        self.assertEqual(_flirt_interpolation("genericLabel"), "nearestneighbour")
        self.assertEqual(_flirt_interpolation("bSpline"), "spline")

    def test_applywarp_interpolation_uses_nn_not_nearestneighbour(self):
        self.assertEqual(_applywarp_interpolation("nearestNeighbor"), "nn")
        self.assertEqual(_applywarp_interpolation("genericLabel"), "nn")
        self.assertEqual(_applywarp_interpolation("linear"), "trilinear")

    def test_unknown_name_passes_through_both_mappings(self):
        self.assertEqual(_flirt_interpolation("trilinear"), "trilinear")
        self.assertEqual(_applywarp_interpolation("nn"), "nn")


class FslFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.fixed = self._touch("fixed.nii.gz")
        self.moving = self._touch("moving.nii.gz")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _touch(self, name: str) -> Path:
        path = self.tmp / name
        path.touch()
        return path


class RunFastTests(FslFixture):
    def test_builds_command_and_returns_pve_paths(self):
        out_prefix = self.tmp / "out" / "seg"
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/fast"), patch(
            "mrsiprep.interfaces.fsl.run_checked"
        ) as run_checked:
            result = run_fast(self.fixed, out_prefix)

        cmd = run_checked.call_args[0][0]
        self.assertEqual(cmd[0], "fast")
        self.assertIn(str(self.fixed), cmd)
        self.assertEqual(result["CSF"], out_prefix.parent / f"{out_prefix.name}_pve_0.nii.gz")
        self.assertEqual(result["GM"], out_prefix.parent / f"{out_prefix.name}_pve_1.nii.gz")
        self.assertEqual(result["WM"], out_prefix.parent / f"{out_prefix.name}_pve_2.nii.gz")


class RegisterFlirtUsesqformTests(FslFixture):
    def test_single_stage_command_with_no_dof_or_cost(self):
        out_prefix = self.tmp / "out" / "mrsi_to_t1"
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/flirt"), patch(
            "mrsiprep.interfaces.fsl.run_cli"
        ) as run_cli:
            result = register_flirt(self.fixed, self.moving, out_prefix, flirt_init="usesqform")

        # usesqform is a single-stage direct apply -- one flirt call plus the inversion.
        flirt_calls = [c for c in run_cli.call_args_list if c[0][0][0] == "flirt"]
        self.assertEqual(len(flirt_calls), 1)
        cmd = flirt_calls[0][0][0]
        self.assertIn("-usesqform", cmd)
        self.assertNotIn("-dof", cmd)
        self.assertEqual(result["forward"], [out_prefix.with_suffix(".flirt.mat")])
        self.assertEqual(result["inverse"], [out_prefix.with_suffix(".flirt_inv.mat")])


class RegisterFlirtSeededTests(FslFixture):
    def test_two_stage_seed_then_refine(self):
        out_prefix = self.tmp / "out" / "mrsi_to_t1"
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/flirt"), patch(
            "mrsiprep.interfaces.fsl.run_cli"
        ) as run_cli:
            register_flirt(self.fixed, self.moving, out_prefix, flirt_dof=6, flirt_cost="corratio", flirt_nosearch=True)

        flirt_calls = [c[0][0] for c in run_cli.call_args_list if c[0][0][0] == "flirt"]
        self.assertEqual(len(flirt_calls), 2)
        seed_cmd, refine_cmd = flirt_calls
        self.assertIn("-usesqform", seed_cmd)
        self.assertIn("-init", refine_cmd)
        self.assertIn("-nosearch", refine_cmd)
        self.assertEqual(refine_cmd[refine_cmd.index("-dof") + 1], "6")
        self.assertEqual(refine_cmd[refine_cmd.index("-cost") + 1], "corratio")

    def test_fixed_mask_becomes_refweight_on_refine_stage_only(self):
        out_prefix = self.tmp / "out" / "mrsi_to_t1"
        mask = self._touch("mask.nii.gz")
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/flirt"), patch(
            "mrsiprep.interfaces.fsl.run_cli"
        ) as run_cli:
            register_flirt(self.fixed, self.moving, out_prefix, fixed_mask=mask)

        flirt_calls = [c[0][0] for c in run_cli.call_args_list if c[0][0][0] == "flirt"]
        seed_cmd, refine_cmd = flirt_calls
        self.assertNotIn("-refweight", seed_cmd)
        self.assertIn("-refweight", refine_cmd)
        self.assertIn(str(mask), refine_cmd)


class RegisterFlirtInvalidInitTests(FslFixture):
    def test_unsupported_init_mode_raises(self):
        out_prefix = self.tmp / "out" / "mrsi_to_t1"
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/flirt"):
            with self.assertRaisesRegex(FSLError, "Unsupported FLIRT initialization mode"):
                register_flirt(self.fixed, self.moving, out_prefix, flirt_init="bogus")


class RegridMaskOntoTests(FslFixture):
    def test_builds_nearest_neighbor_flirt_command(self):
        mask = self._touch("mask.nii.gz")
        out_path = self.tmp / "regridded" / "mask.nii.gz"
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/flirt"), patch(
            "mrsiprep.interfaces.fsl.run_cli"
        ) as run_cli:
            result = _regrid_mask_onto(mask, self.fixed, out_path)

        self.assertEqual(result, out_path)
        cmd = run_cli.call_args[0][0]
        self.assertIn("-usesqform", cmd)
        self.assertIn("nearestneighbour", cmd)
        self.assertIn(str(mask), cmd)


class RegisterFnirtTests(FslFixture):
    def test_orchestrates_flirt_seed_fnirt_and_invwarp(self):
        out_prefix = self.tmp / "out" / "mrsi_to_t1"
        fixed_mask = self._touch("fixed_mask.nii.gz")
        moving_mask = self._touch("moving_mask.nii.gz")
        flirt_affine = out_prefix.with_suffix(".flirt.mat")
        flirt_inv = out_prefix.with_suffix(".flirt_inv.mat")

        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/x"), patch(
            "mrsiprep.interfaces.fsl.register_flirt", return_value={"forward": [flirt_affine], "inverse": [flirt_inv]}
        ) as register_flirt_mock, patch("mrsiprep.interfaces.fsl.run_cli") as run_cli:
            result = register_fnirt(
                self.fixed, self.moving, out_prefix, fixed_mask=fixed_mask, moving_mask=moving_mask, warpres=(8, 8, 8),
            )

        register_flirt_mock.assert_called_once()
        fnirt_calls = [c[0][0] for c in run_cli.call_args_list if c[0][0][0] == "fnirt"]
        self.assertEqual(len(fnirt_calls), 1)
        fnirt_cmd = fnirt_calls[0]
        self.assertTrue(any(arg == f"--aff={flirt_affine}" for arg in fnirt_cmd))
        self.assertTrue(any(arg == "--warpres=8,8,8" for arg in fnirt_cmd))

        invwarp_calls = [c[0][0] for c in run_cli.call_args_list if c[0][0][0] == "invwarp"]
        self.assertEqual(len(invwarp_calls), 1)

        warp = out_prefix.with_suffix(".fnirt_warp.nii.gz")
        warp_inv = out_prefix.with_suffix(".fnirt_warp_inv.nii.gz")
        # fnirt --aff bakes the affine in: forward warp is listed before the
        # affine, matching apply_transforms()'s "warp alone, no --premat" convention.
        self.assertEqual(result["forward"], [warp, flirt_affine])
        self.assertEqual(result["inverse"], [flirt_inv, warp_inv])

    def test_default_warpres_used_when_not_supplied(self):
        out_prefix = self.tmp / "out" / "mrsi_to_t1"
        fixed_mask = self._touch("fixed_mask.nii.gz")
        moving_mask = self._touch("moving_mask.nii.gz")

        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/x"), patch(
            "mrsiprep.interfaces.fsl.register_flirt",
            return_value={"forward": [out_prefix.with_suffix(".flirt.mat")], "inverse": [out_prefix.with_suffix(".flirt_inv.mat")]},
        ), patch("mrsiprep.interfaces.fsl.run_cli") as run_cli:
            register_fnirt(self.fixed, self.moving, out_prefix, fixed_mask=fixed_mask, moving_mask=moving_mask)

        fnirt_cmd = next(c[0][0] for c in run_cli.call_args_list if c[0][0][0] == "fnirt")
        self.assertTrue(any(arg == "--warpres=10,10,10" for arg in fnirt_cmd))


class InvertAffineTests(FslFixture):
    def test_builds_convert_xfm_inverse_command(self):
        affine = self._touch("mrsi_to_t1.flirt.mat")
        inverse = self.tmp / "mrsi_to_t1.flirt_inv.mat"
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/convert_xfm"), patch(
            "mrsiprep.interfaces.fsl.run_cli"
        ) as run_cli:
            _invert_affine(affine, inverse)

        cmd = run_cli.call_args[0][0]
        self.assertEqual(cmd[0], "convert_xfm")
        self.assertIn("-inverse", cmd)
        self.assertIn(str(affine), cmd)


class ApplyAffineAndWarpTests(FslFixture):
    def test_apply_affine_builds_expected_command(self):
        affine = self._touch("mrsi_to_t1.flirt.mat")
        out_path = self.tmp / "out.nii.gz"
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/flirt"), patch(
            "mrsiprep.interfaces.fsl.run_cli"
        ) as run_cli:
            _apply_affine(self.fixed, self.moving, affine, out_path, interpolation="nearestNeighbor")

        cmd = run_cli.call_args[0][0]
        self.assertEqual(cmd[0], "flirt")
        self.assertIn("nearestneighbour", cmd)
        self.assertIn(str(affine), cmd)

    def test_apply_warp_without_postmat(self):
        warp = self._touch("mrsi_to_t1.fnirt_warp.nii.gz")
        out_path = self.tmp / "out.nii.gz"
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/applywarp"), patch(
            "mrsiprep.interfaces.fsl.run_cli"
        ) as run_cli:
            _apply_warp(self.fixed, self.moving, warp, out_path, interpolation="linear")

        cmd = run_cli.call_args[0][0]
        self.assertFalse(any(arg.startswith("--postmat=") for arg in cmd))

    def test_apply_warp_with_postmat(self):
        warp = self._touch("mrsi_to_t1.fnirt_warp.nii.gz")
        postmat = self._touch("t1_to_mni.flirt.mat")
        out_path = self.tmp / "out.nii.gz"
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/local/fsl/bin/applywarp"), patch(
            "mrsiprep.interfaces.fsl.run_cli"
        ) as run_cli:
            _apply_warp(self.fixed, self.moving, warp, out_path, interpolation="linear", postmat=postmat)

        cmd = run_cli.call_args[0][0]
        self.assertIn(f"--postmat={postmat}", cmd)


if __name__ == "__main__":
    unittest.main()

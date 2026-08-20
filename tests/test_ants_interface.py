import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.interfaces.ants import (
    ANTsError,
    _as_image_path,
    _cli_interpolation,
    _cli_transform_code,
    _copy_required,
    _itk_thread_env,
    _resolve_type_of_transform,
    apply_transforms,
    apply_transforms_cli,
    register,
    register_cli,
    require_cli,
    save_all_transforms,
)


class ResolveTypeOfTransformTests(unittest.TestCase):
    def test_full_preset_name_passes_through_verbatim(self):
        self.assertEqual(_resolve_type_of_transform("SyN"), "SyN")
        self.assertEqual(_resolve_type_of_transform("Rigid"), "Rigid")

    def test_short_code_is_wrapped_as_antsregistrationsyn(self):
        self.assertEqual(_resolve_type_of_transform("sr"), "antsRegistrationSyN[sr]")


class CliTransformCodeTests(unittest.TestCase):
    def test_known_preset_maps_to_short_code(self):
        self.assertEqual(_cli_transform_code("Rigid"), "r")
        self.assertEqual(_cli_transform_code("SyN"), "s")
        self.assertEqual(_cli_transform_code("SyNRA"), "s")

    def test_already_short_code_passes_through(self):
        self.assertEqual(_cli_transform_code("sr"), "sr")
        self.assertEqual(_cli_transform_code("a"), "a")


class CliInterpolationTests(unittest.TestCase):
    def test_known_names_map_to_ants_cli_spelling(self):
        self.assertEqual(_cli_interpolation("linear"), "Linear")
        self.assertEqual(_cli_interpolation("nearestNeighbor"), "NearestNeighbor")
        self.assertEqual(_cli_interpolation("genericLabel"), "GenericLabel")
        self.assertEqual(_cli_interpolation("bSpline"), "BSpline")

    def test_unknown_name_passes_through(self):
        self.assertEqual(_cli_interpolation("Linear"), "Linear")


class ItkThreadEnvTests(unittest.TestCase):
    def test_none_is_a_no_op(self):
        before = dict(os.environ)
        with _itk_thread_env(None):
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(dict(os.environ), before)

    def test_sets_and_restores_previous_value(self):
        with patch.dict(os.environ, {"ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS": "2"}):
            with _itk_thread_env(8):
                self.assertEqual(os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"], "8")
            self.assertEqual(os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"], "2")

    def test_sets_and_clears_when_previously_unset(self):
        os.environ.pop("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", None)
        with _itk_thread_env(4):
            self.assertEqual(os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"], "4")
        self.assertNotIn("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", os.environ)

    def test_clamps_to_at_least_one(self):
        with _itk_thread_env(0):
            self.assertEqual(os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"], "1")


class RequireCliTests(unittest.TestCase):
    def test_raises_when_command_not_on_path(self):
        with patch("mrsiprep.interfaces.ants.shutil.which", return_value=None):
            with self.assertRaisesRegex(ANTsError, "antsRegistrationSyN.sh"):
                require_cli("antsRegistrationSyN.sh")

    def test_returns_resolved_path_when_found(self):
        with patch("mrsiprep.interfaces.ants.shutil.which", return_value="/usr/bin/antsRegistrationSyN.sh"):
            self.assertEqual(require_cli("antsRegistrationSyN.sh"), "/usr/bin/antsRegistrationSyN.sh")


class AsImagePathTests(unittest.TestCase):
    def test_raises_for_missing_path(self):
        with self.assertRaisesRegex(ANTsError, "does not exist"):
            _as_image_path("/no/such/file.nii.gz")

    def test_accepts_existing_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "t1w.nii.gz"
            path.touch()
            self.assertEqual(_as_image_path(path), path)

    def test_writes_nibabel_image_to_a_temp_file(self):
        image = nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4))
        out = _as_image_path(image)
        try:
            self.assertTrue(out.exists())
            self.assertTrue(out.name.endswith(".nii.gz"))
        finally:
            out.unlink(missing_ok=True)

    def test_raises_for_unsupported_type(self):
        with self.assertRaisesRegex(ANTsError, "path.*image"):
            _as_image_path(12345)


class CopyRequiredTests(unittest.TestCase):
    def test_raises_when_source_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ANTsError, "did not create expected transform"):
                _copy_required(Path(tmpdir) / "missing.mat", Path(tmpdir) / "out.mat")

    def test_copies_when_source_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "src.mat"
            source.write_text("affine")
            target = Path(tmpdir) / "nested" / "out.mat"
            _copy_required(source, target)
            self.assertEqual(target.read_text(), "affine")


class SaveAllTransformsTests(unittest.TestCase):
    def test_categorizes_forward_and_inverse_by_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            warp = root / "src1Warp.nii.gz"
            affine = root / "src0GenericAffine.mat"
            inv_warp = root / "src1InverseWarp.nii.gz"
            for path in (warp, affine, inv_warp):
                path.touch()
            ants_tx = {"fwdtransforms": [str(warp), str(affine)], "invtransforms": [str(affine), str(inv_warp)]}
            out_prefix = root / "out" / "mrsi_to_t1"

            outputs = save_all_transforms(ants_tx, out_prefix)

            self.assertEqual(outputs["forward"], [out_prefix.with_suffix(".syn.nii.gz"), out_prefix.with_suffix(".affine.mat")])
            self.assertEqual(outputs["inverse"], [out_prefix.with_suffix(".affine_inv.mat"), out_prefix.with_suffix(".syn_inv.nii.gz")])
            for path in outputs["forward"] + outputs["inverse"]:
                self.assertTrue(path.exists())

    def test_unrecognized_filename_falls_back_to_prefixed_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            other = root / "src.other"
            other.touch()
            ants_tx = {"fwdtransforms": [str(other)], "invtransforms": []}
            out_prefix = root / "out" / "mrsi_to_t1"

            outputs = save_all_transforms(ants_tx, out_prefix)

            self.assertEqual(outputs["forward"], [out_prefix.parent / f"{out_prefix.name}.{other.name}"])
            self.assertTrue(outputs["forward"][0].exists())


class RegisterCliFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.fixed = self._touch("fixed.nii.gz")
        self.moving = self._touch("moving.nii.gz")
        self.out_prefix = self.tmp / "out" / "mrsi_to_t1"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _touch(self, name: str) -> Path:
        path = self.tmp / name
        path.touch()
        return path


class RegisterCliWithWarpTests(RegisterCliFixture):
    def test_syn_registration_produces_warp_and_affine_pair(self):
        def fake_run_cli(cmd, **_kwargs):
            # antsRegistrationSyN.sh's own output-file naming convention.
            prefix = Path(cmd[cmd.index("-o") + 1])
            (prefix.parent / f"{prefix.name}0GenericAffine.mat").touch()
            (prefix.parent / f"{prefix.name}1Warp.nii.gz").touch()
            (prefix.parent / f"{prefix.name}1InverseWarp.nii.gz").touch()

        with patch("mrsiprep.interfaces.ants.require_cli", return_value="/usr/bin/antsRegistrationSyN.sh"), patch(
            "mrsiprep.interfaces.ants.run_cli", side_effect=fake_run_cli
        ) as run_cli:
            outputs = register_cli(self.fixed, self.moving, self.out_prefix, transform="sr")

        cmd = run_cli.call_args[0][0]
        self.assertEqual(cmd[0], "antsRegistrationSyN.sh")
        self.assertIn(str(self.fixed), cmd)
        self.assertIn(str(self.moving), cmd)
        self.assertEqual(outputs["forward"], [self.out_prefix.with_suffix(".syn.nii.gz"), self.out_prefix.with_suffix(".affine.mat")])
        self.assertEqual(outputs["inverse"], [self.out_prefix.with_suffix(".affine_inv.mat"), self.out_prefix.with_suffix(".syn_inv.nii.gz")])
        for path in outputs["forward"] + outputs["inverse"]:
            self.assertTrue(path.exists())

    def test_fixed_mask_is_passed_as_dash_x(self):
        mask = self._touch("mask.nii.gz")

        def fake_run_cli(cmd, **_kwargs):
            prefix = Path(cmd[cmd.index("-o") + 1])
            (prefix.parent / f"{prefix.name}0GenericAffine.mat").touch()
            (prefix.parent / f"{prefix.name}1Warp.nii.gz").touch()
            (prefix.parent / f"{prefix.name}1InverseWarp.nii.gz").touch()

        with patch("mrsiprep.interfaces.ants.require_cli", return_value="/usr/bin/antsRegistrationSyN.sh"), patch(
            "mrsiprep.interfaces.ants.run_cli", side_effect=fake_run_cli
        ) as run_cli:
            register_cli(self.fixed, self.moving, self.out_prefix, fixed_mask=mask)

        cmd = run_cli.call_args[0][0]
        self.assertIn("-x", cmd)
        self.assertIn(str(mask), cmd)


class RegisterCliRigidOnlyTests(RegisterCliFixture):
    def test_rigid_only_registration_produces_affine_only_pair(self):
        """MIDAS-mode ('Rigid') registration produces no deformable warp;
        register_cli must emit the affine-only transform pair rather than
        looking for a Warp file that will never exist."""

        def fake_run_cli(cmd, **_kwargs):
            prefix = Path(cmd[cmd.index("-o") + 1])
            (prefix.parent / f"{prefix.name}0GenericAffine.mat").touch()
            # No 1Warp.nii.gz / 1InverseWarp.nii.gz for a rigid-only run.

        with patch("mrsiprep.interfaces.ants.require_cli", return_value="/usr/bin/antsRegistrationSyN.sh"), patch(
            "mrsiprep.interfaces.ants.run_cli", side_effect=fake_run_cli
        ) as run_cli:
            outputs = register_cli(self.fixed, self.moving, self.out_prefix, transform="Rigid")

        cmd = run_cli.call_args[0][0]
        self.assertIn("r", cmd[cmd.index("-t") + 1])
        self.assertEqual(outputs["forward"], [self.out_prefix.with_suffix(".affine.mat")])
        self.assertEqual(outputs["inverse"], [self.out_prefix.with_suffix(".affine_inv.mat")])
        for path in outputs["forward"] + outputs["inverse"]:
            self.assertTrue(path.exists())

    def test_raises_when_affine_never_materializes(self):
        with patch("mrsiprep.interfaces.ants.require_cli", return_value="/usr/bin/antsRegistrationSyN.sh"), patch(
            "mrsiprep.interfaces.ants.run_cli"
        ):
            with self.assertRaisesRegex(ANTsError, "did not create expected transform"):
                register_cli(self.fixed, self.moving, self.out_prefix, transform="Rigid")


class ApplyTransformsCliTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.fixed = self._touch("fixed.nii.gz")
        self.moving = self._touch("moving.nii.gz")
        self.out_path = self.tmp / "out" / "warped.nii.gz"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _touch(self, name: str) -> Path:
        path = self.tmp / name
        path.touch()
        return path

    def test_raises_when_no_transform_files_exist(self):
        missing = self.tmp / "does_not_exist.affine.mat"
        with self.assertRaisesRegex(ANTsError, "No transform files exist"):
            apply_transforms_cli(self.fixed, self.moving, [missing], self.out_path)

    def test_forward_affine_is_passed_without_inversion(self):
        affine = self._touch("mrsi_to_t1.affine.mat")
        with patch("mrsiprep.interfaces.ants.require_cli", return_value="/usr/bin/antsApplyTransforms"), patch(
            "mrsiprep.interfaces.ants.run_cli"
        ) as run_cli:
            result = apply_transforms_cli(self.fixed, self.moving, [affine], self.out_path)

        self.assertEqual(result, self.out_path)
        cmd = run_cli.call_args[0][0]
        self.assertEqual(cmd[0], "antsApplyTransforms")
        self.assertIn("-t", cmd)
        self.assertIn(str(affine), cmd)

    def test_inverse_affine_is_passed_with_invert_flag(self):
        inv_affine = self._touch("t1_to_mrsi.affine_inv.mat")
        with patch("mrsiprep.interfaces.ants.require_cli", return_value="/usr/bin/antsApplyTransforms"), patch(
            "mrsiprep.interfaces.ants.run_cli"
        ) as run_cli:
            apply_transforms_cli(self.fixed, self.moving, [inv_affine], self.out_path)

        cmd = run_cli.call_args[0][0]
        self.assertIn(f"[{inv_affine},1]", cmd)

    def test_interpolation_is_translated_to_ants_cli_spelling(self):
        affine = self._touch("mrsi_to_t1.affine.mat")
        with patch("mrsiprep.interfaces.ants.require_cli", return_value="/usr/bin/antsApplyTransforms"), patch(
            "mrsiprep.interfaces.ants.run_cli"
        ) as run_cli:
            apply_transforms_cli(self.fixed, self.moving, [affine], self.out_path, interpolation="genericLabel")

        cmd = run_cli.call_args[0][0]
        self.assertIn("GenericLabel", cmd)


class RegisterFallsBackToCliTests(unittest.TestCase):
    """antspyx is not installed in the test/CI environment, so `register()`
    and `apply_transforms()` must always fall through to their CLI-backed
    twins rather than raising."""

    def test_register_falls_back_to_register_cli_when_antspyx_missing(self):
        with patch("mrsiprep.interfaces.ants._import_ants", side_effect=ANTsError("no antspyx")), patch(
            "mrsiprep.interfaces.ants.register_cli", return_value={"forward": [], "inverse": []}
        ) as register_cli_mock:
            result = register("fixed.nii.gz", "moving.nii.gz", "out_prefix", transform="sr")

        register_cli_mock.assert_called_once()
        self.assertEqual(result, {"forward": [], "inverse": []})

    def test_apply_transforms_falls_back_to_cli_when_antspyx_missing(self):
        with patch("mrsiprep.interfaces.ants._import_ants", side_effect=ANTsError("no antspyx")), patch(
            "mrsiprep.interfaces.ants.apply_transforms_cli", return_value=Path("out.nii.gz")
        ) as apply_cli_mock:
            result = apply_transforms("fixed.nii.gz", "moving.nii.gz", ["a.mat"], "out.nii.gz")

        apply_cli_mock.assert_called_once()
        self.assertEqual(result, Path("out.nii.gz"))

    def test_apply_transforms_without_out_path_raises_when_antspyx_missing(self):
        with patch("mrsiprep.interfaces.ants._import_ants", side_effect=ANTsError("no antspyx")):
            with self.assertRaisesRegex(ANTsError, "requires an output path"):
                apply_transforms("fixed.nii.gz", "moving.nii.gz", ["a.mat"], out_path=None)


if __name__ == "__main__":
    unittest.main()

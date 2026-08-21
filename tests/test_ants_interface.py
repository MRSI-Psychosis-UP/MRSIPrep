import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import nibabel as nib
import numpy as np

from mrsiprep.interfaces.ants import (
    ANTsError,
    Registration,
    _as_image_path,
    _cli_interpolation,
    _cli_transform_code,
    _copy_required,
    _itk_thread_env,
    _load_ants_image,
    _resolve_type_of_transform,
    apply_transforms,
    apply_transforms_cli,
    register,
    register_cli,
    require_cli,
    run_cli,
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
        # Unlike FSL's apply_transforms(), ants.py's apply_transforms_cli()
        # checks require_cli("antsApplyTransforms") before the transform-list
        # check, so the CLI must be mocked as present for this path to be
        # reached at all.
        missing = self.tmp / "does_not_exist.affine.mat"
        with patch("mrsiprep.interfaces.ants.require_cli", return_value="/usr/bin/antsApplyTransforms"):
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


class LoadAntsImageTests(unittest.TestCase):
    def test_existing_path_is_read_via_ants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "t1w.nii.gz"
            path.touch()
            fake_ants = MagicMock()
            fake_ants.image_read.return_value = "loaded-image"
            with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants):
                result = _load_ants_image(path)
        fake_ants.image_read.assert_called_once_with(str(path))
        self.assertEqual(result, "loaded-image")

    def test_missing_path_raises(self):
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=MagicMock()):
            with self.assertRaisesRegex(ANTsError, "does not exist"):
                _load_ants_image("/no/such/file.nii.gz")

    def test_nibabel_image_is_saved_to_a_cleaned_up_temp_file(self):
        image = nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4))
        fake_ants = MagicMock()
        fake_ants.image_read.return_value = "loaded-image"
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants):
            result = _load_ants_image(image)
        temp_path_str = fake_ants.image_read.call_args[0][0]
        self.assertTrue(temp_path_str.endswith(".nii.gz"))
        self.assertFalse(Path(temp_path_str).exists())  # cleaned up in the finally block
        self.assertEqual(result, "loaded-image")

    def test_antsimage_instance_passes_through_unchanged(self):
        fake_image = type("ANTsImage", (), {})()
        fake_ants = MagicMock()
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants):
            result = _load_ants_image(fake_image)
        self.assertIs(result, fake_image)
        fake_ants.image_read.assert_not_called()

    def test_unsupported_type_raises(self):
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=MagicMock()):
            with self.assertRaisesRegex(ANTsError, "path, nibabel image, or ANTsImage"):
                _load_ants_image(12345)


class RegisterAntspyxSuccessTests(unittest.TestCase):
    """antspyx isn't installed in CI, so these mock _import_ants() to
    *succeed* -- covering register()'s try-block, which is otherwise never
    exercised (RegisterFallsBackToCliTests only covers _import_ants failing)."""

    def test_success_path_calls_antspyx_and_skips_cli(self):
        fake_ants = MagicMock()
        fake_ants.registration.return_value = {"fwdtransforms": ["x"], "invtransforms": ["y"]}
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants), patch(
            "mrsiprep.interfaces.ants._load_ants_image", side_effect=lambda img: f"loaded:{img}"
        ), patch("mrsiprep.interfaces.ants.save_all_transforms", return_value={"forward": [], "inverse": []}) as save_fn, patch(
            "mrsiprep.interfaces.ants.register_cli"
        ) as register_cli_mock:
            result = register("fixed.nii.gz", "moving.nii.gz", "out_prefix", transform="sr")

        register_cli_mock.assert_not_called()
        kwargs = fake_ants.registration.call_args.kwargs
        self.assertEqual(kwargs["fixed"], "loaded:fixed.nii.gz")
        self.assertEqual(kwargs["moving"], "loaded:moving.nii.gz")
        self.assertIsNone(kwargs["fixed_mask"])
        self.assertIsNone(kwargs["moving_mask"])
        self.assertEqual(kwargs["type_of_transform"], "antsRegistrationSyN[sr]")
        save_fn.assert_called_once_with({"fwdtransforms": ["x"], "invtransforms": ["y"]}, "out_prefix")
        self.assertEqual(result, {"forward": [], "inverse": []})

    def test_full_preset_transform_name_passed_verbatim(self):
        fake_ants = MagicMock()
        fake_ants.registration.return_value = {}
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants), patch(
            "mrsiprep.interfaces.ants._load_ants_image", side_effect=lambda img: img
        ), patch("mrsiprep.interfaces.ants.save_all_transforms", return_value={}):
            register("fixed.nii.gz", "moving.nii.gz", "out_prefix", transform="SyN")
        self.assertEqual(fake_ants.registration.call_args.kwargs["type_of_transform"], "SyN")

    def test_masks_are_loaded_when_provided(self):
        fake_ants = MagicMock()
        fake_ants.registration.return_value = {}
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants), patch(
            "mrsiprep.interfaces.ants._load_ants_image", side_effect=lambda img: f"loaded:{img}"
        ), patch("mrsiprep.interfaces.ants.save_all_transforms", return_value={}):
            register("fixed.nii.gz", "moving.nii.gz", "out_prefix", fixed_mask="fmask.nii.gz", moving_mask="mmask.nii.gz")
        kwargs = fake_ants.registration.call_args.kwargs
        self.assertEqual(kwargs["fixed_mask"], "loaded:fmask.nii.gz")
        self.assertEqual(kwargs["moving_mask"], "loaded:mmask.nii.gz")

    def test_non_antserror_exception_propagates_without_cli_fallback(self):
        fake_ants = MagicMock()
        fake_ants.registration.side_effect = RuntimeError("antspyx internal crash")
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants), patch(
            "mrsiprep.interfaces.ants._load_ants_image", side_effect=lambda img: img
        ), patch("mrsiprep.interfaces.ants.register_cli") as register_cli_mock:
            with self.assertRaisesRegex(RuntimeError, "antspyx internal crash"):
                register("fixed.nii.gz", "moving.nii.gz", "out_prefix")
        register_cli_mock.assert_not_called()

    def test_antserror_raised_mid_pipeline_still_falls_back_to_cli(self):
        """The except clause wraps the whole antspyx pipeline, not just
        _import_ants() -- an ANTsError from anywhere inside it also triggers
        the CLI fallback, not just antspyx being absent."""
        fake_ants = MagicMock()
        fake_ants.registration.side_effect = ANTsError("registration blew up")
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants), patch(
            "mrsiprep.interfaces.ants._load_ants_image", side_effect=lambda img: img
        ), patch("mrsiprep.interfaces.ants.register_cli", return_value={"forward": [], "inverse": []}) as register_cli_mock:
            result = register("fixed.nii.gz", "moving.nii.gz", "out_prefix")
        register_cli_mock.assert_called_once()
        self.assertEqual(result, {"forward": [], "inverse": []})


class ApplyTransformsAntspyxSuccessTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.transform = self.tmp / "mrsi_to_t1.affine.mat"
        self.transform.touch()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_returns_warped_image_directly_when_no_out_path(self):
        fake_ants = MagicMock()
        fake_ants.apply_transforms.return_value = "warped-image"
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants), patch(
            "mrsiprep.interfaces.ants._load_ants_image", side_effect=lambda img: f"loaded:{img}"
        ):
            result = apply_transforms("fixed.nii.gz", "moving.nii.gz", [self.transform], out_path=None)
        self.assertEqual(result, "warped-image")
        fake_ants.image_write.assert_not_called()
        kwargs = fake_ants.apply_transforms.call_args.kwargs
        self.assertEqual(kwargs["transformlist"], [str(self.transform)])
        self.assertEqual(kwargs["interpolator"], "linear")

    def test_writes_and_returns_out_path_when_given(self):
        out_path = self.tmp / "out" / "warped.nii.gz"
        fake_ants = MagicMock()
        fake_ants.apply_transforms.return_value = "warped-image"
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants), patch(
            "mrsiprep.interfaces.ants._load_ants_image", side_effect=lambda img: img
        ):
            result = apply_transforms("fixed.nii.gz", "moving.nii.gz", [self.transform], out_path=out_path)
        self.assertEqual(result, out_path)
        fake_ants.image_write.assert_called_once_with("warped-image", str(out_path))

    def test_missing_transforms_with_out_path_falls_back_to_cli(self):
        """A transform list that resolves to no existing files raises
        ANTsError internally, which this function's own except-clause then
        catches -- since out_path is given, it retries via the CLI backend
        instead of propagating the "No transform files exist" error."""
        missing = self.tmp / "does_not_exist.affine.mat"
        out_path = self.tmp / "warped.nii.gz"
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=MagicMock()), patch(
            "mrsiprep.interfaces.ants.apply_transforms_cli", return_value=out_path
        ) as apply_cli_mock:
            result = apply_transforms("fixed.nii.gz", "moving.nii.gz", [missing], out_path=out_path)
        apply_cli_mock.assert_called_once()
        self.assertEqual(result, out_path)

    def test_missing_transforms_without_out_path_raises_output_path_message(self):
        """The original "No transform files exist" ANTsError is swallowed by
        this function's own except-clause; with no out_path to retry the CLI
        against, it re-raises a different, output-path-specific message."""
        missing = self.tmp / "does_not_exist.affine.mat"
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=MagicMock()):
            with self.assertRaisesRegex(ANTsError, "requires an output path"):
                apply_transforms("fixed.nii.gz", "moving.nii.gz", [missing], out_path=None)


class RegistrationFacadeTests(unittest.TestCase):
    """The Registration class is a facade "matching the mrsitoolbox workflow
    API" -- not used anywhere in the pipeline itself (only the module-level
    register()/apply_transforms() are), but still real, reachable code."""

    def test_register_wraps_transform_verbatim_even_for_full_presets(self):
        """Unlike the module-level register()/_resolve_type_of_transform(),
        this facade always wraps transform in antsRegistrationSyN[...], even
        for full preset names like "SyN" -- and has no try/except, so an
        antspyx-missing failure propagates instead of falling back to CLI."""
        fake_ants = MagicMock()
        fake_ants.registration.return_value = "tx-result"
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants), patch(
            "mrsiprep.interfaces.ants._load_ants_image", side_effect=lambda img: f"loaded:{img}"
        ):
            tx, elapsed = Registration().register("fixed.nii.gz", "moving.nii.gz", transform="SyN")
        self.assertEqual(fake_ants.registration.call_args.kwargs["type_of_transform"], "antsRegistrationSyN[SyN]")
        self.assertEqual(tx, "tx-result")
        self.assertIsInstance(elapsed, float)

    def test_register_propagates_when_antspyx_missing(self):
        with patch("mrsiprep.interfaces.ants._import_ants", side_effect=ANTsError("no antspyx")):
            with self.assertRaises(ANTsError):
                Registration().register("fixed.nii.gz", "moving.nii.gz")

    def test_transform_delegates_to_antspyx_apply_transforms(self):
        fake_ants = MagicMock()
        fake_ants.apply_transforms.return_value = "warped"
        with patch("mrsiprep.interfaces.ants._import_ants", return_value=fake_ants), patch(
            "mrsiprep.interfaces.ants._load_ants_image", side_effect=lambda img: img
        ):
            result = Registration().transform("fixed.nii.gz", "moving.nii.gz", [Path("a.mat"), Path("b.mat")])
        self.assertEqual(result, "warped")
        kwargs = fake_ants.apply_transforms.call_args.kwargs
        self.assertEqual(kwargs["transformlist"], ["a.mat", "b.mat"])
        self.assertEqual(kwargs["interpolator"], "linear")

    def test_save_all_transforms_delegates_to_module_level_function(self):
        with patch("mrsiprep.interfaces.ants.save_all_transforms", return_value="saved") as save_fn:
            result = Registration().save_all_transforms({"fwdtransforms": []}, "prefix")
        save_fn.assert_called_once_with({"fwdtransforms": []}, "prefix")
        self.assertEqual(result, "saved")


class RunCliTests(unittest.TestCase):
    def test_no_threads_passes_env_none(self):
        with patch("mrsiprep.interfaces.ants.run_checked") as run_checked_mock:
            run_cli(["antsRegistrationSyN.sh", "-d", "3"])
        run_checked_mock.assert_called_once_with(
            ["antsRegistrationSyN.sh", "-d", "3"], verbose=False, env=None, error_cls=ANTsError, error_prefix="antsRegistrationSyN.sh"
        )

    def test_threads_sets_itk_env_var_in_a_copy_of_os_environ(self):
        os.environ.pop("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", None)
        with patch.dict(os.environ, {"SOME_OTHER_VAR": "keep-me"}, clear=False), patch(
            "mrsiprep.interfaces.ants.run_checked"
        ) as run_checked_mock:
            run_cli(["antsApplyTransforms"], threads=4)
        env = run_checked_mock.call_args.kwargs["env"]
        self.assertEqual(env["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"], "4")
        self.assertEqual(env["SOME_OTHER_VAR"], "keep-me")
        self.assertNotIn("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", os.environ)


if __name__ == "__main__":
    unittest.main()

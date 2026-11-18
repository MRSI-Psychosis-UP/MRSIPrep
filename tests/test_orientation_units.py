import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.mrsi.orientation import _corrected_grid, _pick_orientation_reference, correct_mrsi_orientation
from mrsiprep.registration.transforms import ants_transform_prefix


class AntsTransformPrefixOrientStageTests(unittest.TestCase):
    def test_orient_stage_is_distinct_from_the_mrsi_to_t1w_stage(self):
        root = Path("/out")
        orient = ants_transform_prefix(root, "S001", "V1", "orient")
        mrsi = ants_transform_prefix(root, "S001", "V1", "mrsi")
        self.assertNotEqual(orient, mrsi)
        self.assertTrue(str(orient).endswith("sub-S001_ses-V1_desc-mrsi_orientfix"))

    def test_orient_stage_backend_suffix_matches_the_mrsi_stage_convention(self):
        root = Path("/out")
        orient_fsl = ants_transform_prefix(root, "S001", "V1", "orient", backend="fsl")
        self.assertTrue(str(orient_fsl).endswith("sub-S001_ses-V1_desc-mrsi_orientfix_fsl"))


def _config(root: Path, **overrides):
    base = dict(
        derivative_dir=root / "derivatives",
        overwrite=False,
        overwrite_t1_reg=False,
        ref_met="CrPCr",
        registration_backend="ants",
        fsl_cost="corratio",
        verbose=1,
        nthreads=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _vol(shape=(4, 4, 4), value=1.0, affine=None):
    return nib.Nifti1Image(np.full(shape, value, dtype=np.float32), np.eye(4) if affine is None else affine)


def _save(path: Path, img: nib.Nifti1Image) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(img, path)
    return path


class PickOrientationReferenceTests(unittest.TestCase):
    def test_prefers_the_configured_ref_met(self):
        maps = {"CrPCr": Path("cr"), "GluGln": Path("glu")}
        self.assertEqual(_pick_orientation_reference(maps, "CrPCr"), Path("cr"))

    def test_falls_back_to_the_first_available_map(self):
        maps = {"GluGln": Path("glu")}
        self.assertEqual(_pick_orientation_reference(maps, "CrPCr"), Path("glu"))

    def test_raises_when_no_maps_are_available(self):
        with self.assertRaises(ValueError):
            _pick_orientation_reference({}, "CrPCr")


class CorrectedGridTests(unittest.TestCase):
    def test_keeps_native_shape_and_spacing_but_the_t1_space_rotation(self):
        native = _vol(shape=(4, 4, 6), affine=np.diag([2.0, 2.0, 3.0, 1.0]))
        # A 90-degree rotation about the z axis, as if T1w-space resampling
        # revealed the MRSI reference was actually rotated relative to its
        # header.
        rotation = np.array([[0.0, -1.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]])
        ref_in_t1 = _vol(shape=(8, 8, 8), affine=rotation @ np.eye(4))

        shape, affine = _corrected_grid(ref_in_t1, native)

        self.assertEqual(shape, (4, 4, 6))
        # Voxel spacing (column norms) matches the native grid, not T1w's.
        zooms = np.linalg.norm(affine[:3, :3], axis=0)
        np.testing.assert_allclose(zooms, [2.0, 2.0, 3.0], atol=1e-5)
        # The rotation (direction, ignoring scale) matches the T1w-space image.
        native_dirs = affine[:3, :3] / zooms
        t1_dirs = rotation[:3, :3]
        np.testing.assert_allclose(native_dirs, t1_dirs, atol=1e-5)


class CorrectMrsiOrientationTests(unittest.TestCase):
    def test_applies_the_same_rigid_correction_to_every_map_in_place(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cr = _save(root / "cr.nii.gz", _vol(value=5.0))
            glu = _save(root / "glu.nii.gz", _vol(value=9.0))
            crlb = _save(root / "crlb.nii.gz", _vol(value=12.0))
            t1 = _save(root / "t1.nii.gz", _vol(shape=(8, 8, 8)))
            config = _config(root)

            def _fake_apply_image_transform(fixed, moving, transforms, out_path, **kwargs):
                # Stand-in for the real rigid resample into T1w space: same
                # shape as T1w, identity rotation is fine for this test.
                _save(Path(out_path), _vol(shape=(8, 8, 8)))
                return Path(out_path)

            with patch("mrsiprep.mrsi.orientation.ants_transform_prefix", return_value=root / "xfm" / "orient"), patch(
                "mrsiprep.mrsi.orientation.transform_paths", return_value=[root / "xfm" / "orient.affine.mat"]
            ), patch("mrsiprep.mrsi.orientation.all_exist", return_value=False), patch(
                "mrsiprep.interfaces.ants.register", return_value={"forward": [], "inverse": []}
            ) as register, patch(
                "mrsiprep.mrsi.orientation.apply_image_transform", side_effect=_fake_apply_image_transform
            ):
                result = correct_mrsi_orientation(
                    config, "S001", "V1", {"CrPCr": cr, "GluGln": glu}, t1, crlb_maps={"CrPCr": crlb}
                )

            register.assert_called_once()
            self.assertEqual(set(result), {"CrPCr", "GluGln", "crlb-CrPCr"})
            for path in (cr, glu, crlb):
                img = nib.load(str(path))
                self.assertEqual(img.shape, (4, 4, 4))

    def test_snr_and_linewidth_maps_are_corrected_too(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cr = _save(root / "cr.nii.gz", _vol(value=5.0))
            snr = _save(root / "snr.nii.gz", _vol(value=8.0))
            fwhm = _save(root / "fwhm.nii.gz", _vol(value=0.05))
            t1 = _save(root / "t1.nii.gz", _vol(shape=(8, 8, 8)))
            config = _config(root)

            def _fake_apply_image_transform(fixed, moving, transforms, out_path, **kwargs):
                _save(Path(out_path), _vol(shape=(8, 8, 8)))
                return Path(out_path)

            with patch("mrsiprep.mrsi.orientation.ants_transform_prefix", return_value=root / "xfm" / "orient"), patch(
                "mrsiprep.mrsi.orientation.transform_paths", return_value=[root / "xfm" / "orient.affine.mat"]
            ), patch("mrsiprep.mrsi.orientation.all_exist", return_value=False), patch(
                "mrsiprep.interfaces.ants.register", return_value={"forward": [], "inverse": []}
            ), patch(
                "mrsiprep.mrsi.orientation.apply_image_transform", side_effect=_fake_apply_image_transform
            ):
                result = correct_mrsi_orientation(
                    config, "S001", "V1", {"CrPCr": cr}, t1, snr_map=snr, linewidth_map=fwhm
                )

            self.assertEqual(set(result), {"CrPCr", "snr", "fwhm"})

    def test_reuses_an_existing_transform_without_recomputing_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cr = _save(root / "cr.nii.gz", _vol(value=5.0))
            t1 = _save(root / "t1.nii.gz", _vol(shape=(8, 8, 8)))
            config = _config(root)

            def _fake_apply_image_transform(fixed, moving, transforms, out_path, **kwargs):
                _save(Path(out_path), _vol(shape=(8, 8, 8)))
                return Path(out_path)

            with patch("mrsiprep.mrsi.orientation.ants_transform_prefix", return_value=root / "xfm" / "orient"), patch(
                "mrsiprep.mrsi.orientation.transform_paths", return_value=[root / "xfm" / "orient.affine.mat"]
            ), patch("mrsiprep.mrsi.orientation.all_exist", return_value=True), patch(
                "mrsiprep.interfaces.ants.register"
            ) as register, patch(
                "mrsiprep.mrsi.orientation.apply_image_transform", side_effect=_fake_apply_image_transform
            ):
                correct_mrsi_orientation(config, "S001", "V1", {"CrPCr": cr}, t1)

            register.assert_not_called()

    def test_uses_flirt_dof6_for_the_fsl_backend(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cr = _save(root / "cr.nii.gz", _vol(value=5.0))
            t1 = _save(root / "t1.nii.gz", _vol(shape=(8, 8, 8)))
            config = _config(root, registration_backend="fsl")

            def _fake_apply_image_transform(fixed, moving, transforms, out_path, **kwargs):
                _save(Path(out_path), _vol(shape=(8, 8, 8)))
                return Path(out_path)

            with patch("mrsiprep.mrsi.orientation.ants_transform_prefix", return_value=root / "xfm" / "orient"), patch(
                "mrsiprep.mrsi.orientation.transform_paths", return_value=[root / "xfm" / "orient.flirt.mat"]
            ), patch("mrsiprep.mrsi.orientation.all_exist", return_value=False), patch(
                "mrsiprep.interfaces.fsl.register_flirt", return_value={"forward": [], "inverse": []}
            ) as register_flirt, patch(
                "mrsiprep.mrsi.orientation.apply_image_transform", side_effect=_fake_apply_image_transform
            ):
                correct_mrsi_orientation(config, "S001", "V1", {"CrPCr": cr}, t1)

            register_flirt.assert_called_once()
            self.assertEqual(register_flirt.call_args.kwargs["flirt_dof"], 6)


if __name__ == "__main__":
    unittest.main()

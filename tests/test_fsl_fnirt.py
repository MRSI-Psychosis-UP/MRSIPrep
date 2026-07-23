import unittest
from pathlib import Path

from mrsiprep.interfaces.fsl import default_fnirt_warpres
from mrsiprep.registration.transforms import _is_fsl_transform, transform_paths


class DefaultFnirtWarpresTests(unittest.TestCase):
    def test_scales_to_roughly_2x_voxel_size(self):
        self.assertEqual(default_fnirt_warpres((5.0, 5.0, 5.2)), (10, 10, 10))

    def test_floors_at_6mm_for_high_resolution_input(self):
        self.assertEqual(default_fnirt_warpres((3.4, 3.4, 3.5)), (7, 7, 7))
        self.assertEqual(default_fnirt_warpres((1.0, 1.0, 1.0)), (6, 6, 6))

    def test_respects_custom_floor(self):
        self.assertEqual(default_fnirt_warpres((1.0, 1.0, 1.0), floor_mm=4), (4, 4, 4))


class TransformPathsFSLTests(unittest.TestCase):
    def setUp(self):
        self.prefix = Path("/tmp/sub-01_ses-01_desc-mrsi_to_t1w")

    def test_flirt_only_forward(self):
        paths = transform_paths(self.prefix, "forward", backend="fsl")
        self.assertEqual(paths, [self.prefix.with_suffix(".flirt.mat")])

    def test_flirt_only_inverse(self):
        paths = transform_paths(self.prefix, "inverse", backend="fsl")
        self.assertEqual(paths, [self.prefix.with_suffix(".flirt_inv.mat")])

    def test_deformable_forward_lists_warp_before_affine(self):
        paths = transform_paths(self.prefix, "forward", backend="fsl", deformable=True)
        self.assertEqual(paths, [self.prefix.with_suffix(".fnirt_warp.nii.gz"), self.prefix.with_suffix(".flirt.mat")])

    def test_deformable_inverse_lists_affine_before_warp(self):
        paths = transform_paths(self.prefix, "inverse", backend="fsl", deformable=True)
        self.assertEqual(paths, [self.prefix.with_suffix(".flirt_inv.mat"), self.prefix.with_suffix(".fnirt_warp_inv.nii.gz")])


class IsFSLTransformTests(unittest.TestCase):
    def test_recognizes_flirt_affine(self):
        self.assertTrue(_is_fsl_transform(Path("x.flirt.mat")))
        self.assertTrue(_is_fsl_transform(Path("x.flirt_inv.mat")))

    def test_recognizes_fnirt_warp(self):
        self.assertTrue(_is_fsl_transform(Path("x.fnirt_warp.nii.gz")))
        self.assertTrue(_is_fsl_transform(Path("x.fnirt_warp_inv.nii.gz")))

    def test_rejects_ants_transform(self):
        self.assertFalse(_is_fsl_transform(Path("x.syn.nii.gz")))
        self.assertFalse(_is_fsl_transform(Path("x.affine.mat")))


if __name__ == "__main__":
    unittest.main()

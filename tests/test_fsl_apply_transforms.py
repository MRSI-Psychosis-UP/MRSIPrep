import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mrsiprep.interfaces.fsl import FSLError, apply_transforms


class ApplyTransformsFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.fixed = self._touch("fixed.nii.gz")
        self.moving = self._touch("moving.nii.gz")
        self.out_path = self.tmp / "out" / "resampled.nii.gz"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _touch(self, name: str) -> Path:
        path = self.tmp / name
        path.touch()
        return path

    def _run(self, transforms):
        with patch("mrsiprep.interfaces.fsl.require_cli", return_value="/usr/bin/x"), patch("mrsiprep.interfaces.fsl.run_cli") as run_cli:
            result = apply_transforms(self.fixed, self.moving, transforms, self.out_path)
        return result, run_cli


class NoTransformsTests(ApplyTransformsFixture):
    def test_raises_when_no_transform_files_exist(self):
        missing = self.tmp / "does_not_exist.flirt.mat"
        with self.assertRaisesRegex(FSLError, "No transform files exist"):
            apply_transforms(self.fixed, self.moving, [missing], self.out_path)


class SingleAffineTests(ApplyTransformsFixture):
    def test_applies_flirt_with_single_affine(self):
        affine = self._touch("mrsi_to_t1.flirt.mat")
        result, run_cli = self._run([affine])
        self.assertEqual(result, self.out_path)
        cmd = run_cli.call_args[0][0]
        self.assertEqual(cmd[0], "flirt")
        self.assertIn(str(affine), cmd)

    def test_rejects_multiple_non_flirt_transforms(self):
        # Two files that are neither .flirt.mat nor .fnirt_warp*: falls
        # through both special cases into the final "too many" guard.
        a = self._touch("a.unknown")
        b = self._touch("b.unknown")
        with self.assertRaisesRegex(FSLError, "expects a single affine or FNIRT warp"):
            apply_transforms(self.fixed, self.moving, [a, b], self.out_path)


class ComposedAffinesTests(ApplyTransformsFixture):
    def test_composes_multiple_affines_via_convert_xfm(self):
        mrsi_to_t1 = self._touch("mrsi_to_t1.flirt.mat")
        t1_to_mni = self._touch("t1_to_mni.flirt.mat")
        # Callers list transforms last-applied-first (t1_to_mni first, then
        # mrsi_to_t1) -- convert_xfm -concat must receive them in that same order.
        result, run_cli = self._run([t1_to_mni, mrsi_to_t1])
        self.assertEqual(result, self.out_path)
        calls = [c[0][0] for c in run_cli.call_args_list]
        concat_call = next(cmd for cmd in calls if cmd[0] == "convert_xfm")
        self.assertIn("-concat", concat_call)
        concat_idx = concat_call.index("-concat")
        self.assertEqual(concat_call[concat_idx + 1 :], [str(t1_to_mni), str(mrsi_to_t1)])
        flirt_call = next(cmd for cmd in calls if cmd[0] == "flirt")
        self.assertNotIn(str(mrsi_to_t1), flirt_call)
        self.assertNotIn(str(t1_to_mni), flirt_call)


class WarpTransformTests(ApplyTransformsFixture):
    def test_applies_warp_alone_without_premat(self):
        """Regression test: passing the warp's own seed affine as --premat
        alongside the warp previously collapsed the resampled correlation
        against the ANTs SyN reference from r=0.71 to r=-0.24."""
        warp = self._touch("mrsi_to_t1.fnirt_warp.nii.gz")
        seed_affine = self._touch("mrsi_to_t1.flirt.mat")
        result, run_cli = self._run([warp, seed_affine])
        self.assertEqual(result, self.out_path)
        cmd = run_cli.call_args[0][0]
        self.assertEqual(cmd[0], "applywarp")
        self.assertTrue(any(arg.startswith("--warp=") for arg in cmd))
        self.assertFalse(any(arg.startswith("--premat=") for arg in cmd))
        self.assertFalse(any(arg.startswith("--postmat=") for arg in cmd))

    def test_applies_separate_stage_affine_as_postmat(self):
        """Regression test: a genuinely separate registration stage's affine
        (different filename prefix than the warp) must be applied via
        --postmat, not dropped -- dropping it previously left "MNI-space"
        output actually sitting in T1w space (~65% outside-brain instead of
        ~15-30%)."""
        warp = self._touch("mrsi_to_t1.fnirt_warp.nii.gz")
        other_stage_affine = self._touch("t1_to_mni.flirt.mat")
        result, run_cli = self._run([warp, other_stage_affine])
        self.assertEqual(result, self.out_path)
        cmd = run_cli.call_args[0][0]
        self.assertEqual(cmd[0], "applywarp")
        self.assertIn(f"--postmat={other_stage_affine}", cmd)

    def test_rejects_multiple_warps(self):
        warp_a = self._touch("a.fnirt_warp.nii.gz")
        warp_b = self._touch("b.fnirt_warp.nii.gz")
        with self.assertRaisesRegex(FSLError, "single FNIRT warp"):
            apply_transforms(self.fixed, self.moving, [warp_a, warp_b], self.out_path)

    def test_rejects_multiple_post_warp_affines(self):
        warp = self._touch("mrsi_to_t1.fnirt_warp.nii.gz")
        stage_a = self._touch("t1_to_mni.flirt.mat")
        stage_b = self._touch("mni_to_group.flirt.mat")
        with self.assertRaisesRegex(FSLError, "at most one post-warp affine stage"):
            apply_transforms(self.fixed, self.moving, [warp, stage_a, stage_b], self.out_path)


if __name__ == "__main__":
    unittest.main()

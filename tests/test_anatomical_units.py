import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.workflows.anatomical import create_brain_csf_t1, prepare_anatomical


class PrepareAnatomicalFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.t1_path = self.tmp / "skull.nii.gz"
        self.t1_path.touch()
        self.config = SimpleNamespace(
            bids_dir=self.tmp / "bids",
            bids_filters={},
            derivative_dir=self.tmp / "derivatives",
            registration_t1_target="brain",
            csf_pv_threshold=0.95,
            overwrite_t1_reg=False,
            overwrite=False,
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def _layout(self, raw_t1=None, brain_mask=None, p3=None):
        mock_layout = SimpleNamespace(
            raw_t1=lambda *a, **k: raw_t1,
            brain_mask=lambda *a, **k: brain_mask,
            cat12_probseg=lambda *a, **k: p3,
        )
        return patch(
            "mrsiprep.workflows.anatomical.BIDSLayout",
            return_value=mock_layout,
            **{"from_config.return_value": mock_layout},
        )


class BrainTargetTests(PrepareAnatomicalFixture):
    def test_registers_directly_to_skull_stripped_t1(self):
        raw = self.tmp / "raw.nii.gz"
        mask = self.tmp / "mask.nii.gz"
        with self._layout(raw_t1=raw, brain_mask=mask):
            result = prepare_anatomical(self.config, "01", "01", self.t1_path)

        self.assertEqual(result.registration_t1w, self.t1_path)
        self.assertEqual(result.registration_mask, mask)
        self.assertEqual(result.t1w, self.t1_path)
        self.assertEqual(result.raw_t1w, raw)
        self.assertEqual(result.target_kind, "brain")

    def test_brain_mask_override_takes_priority_over_layout(self):
        override = self.tmp / "override_mask.nii.gz"
        with self._layout(brain_mask=self.tmp / "layout_mask.nii.gz"):
            result = prepare_anatomical(self.config, "01", "01", self.t1_path, brain_mask_override=override)
        self.assertEqual(result.brain_mask, override)


class RawTargetTests(PrepareAnatomicalFixture):
    def test_registers_to_raw_t1_with_no_mask(self):
        self.config.registration_t1_target = "raw"
        raw = self.tmp / "raw.nii.gz"
        with self._layout(raw_t1=raw):
            result = prepare_anatomical(self.config, "01", "01", self.t1_path)
        self.assertEqual(result.registration_t1w, raw)
        self.assertIsNone(result.registration_mask)

    def test_raises_when_raw_t1_missing(self):
        self.config.registration_t1_target = "raw"
        with self._layout(raw_t1=None):
            with self.assertRaisesRegex(FileNotFoundError, "Missing raw T1w acquisition for raw"):
                prepare_anatomical(self.config, "01", "01", self.t1_path)


class BrainCsfTargetTests(PrepareAnatomicalFixture):
    def test_dispatches_to_create_brain_csf_t1(self):
        self.config.registration_t1_target = "brain-csf"
        raw = self.tmp / "raw.nii.gz"
        p3 = self.tmp / "p3.nii.gz"
        composite_t1 = self.tmp / "composite.nii.gz"
        composite_mask = self.tmp / "composite_mask.nii.gz"
        with self._layout(raw_t1=raw, p3=p3), patch(
            "mrsiprep.workflows.anatomical.create_brain_csf_t1", return_value=(composite_t1, composite_mask)
        ) as create_fn:
            result = prepare_anatomical(self.config, "01", "01", self.t1_path)

        create_fn.assert_called_once()
        self.assertEqual(create_fn.call_args.kwargs["skull_t1"], self.t1_path)
        self.assertEqual(create_fn.call_args.kwargs["raw_t1"], raw)
        self.assertEqual(create_fn.call_args.kwargs["p3"], p3)
        self.assertEqual(create_fn.call_args.kwargs["threshold"], 0.95)
        self.assertEqual(result.registration_t1w, composite_t1)
        self.assertEqual(result.registration_mask, composite_mask)

    def test_p3_override_bypasses_layout_lookup(self):
        self.config.registration_t1_target = "brain-csf"
        raw = self.tmp / "raw.nii.gz"
        override_p3 = self.tmp / "override_p3.nii.gz"
        with self._layout(raw_t1=raw, p3=None), patch(
            "mrsiprep.workflows.anatomical.create_brain_csf_t1", return_value=(self.tmp / "a", self.tmp / "b")
        ) as create_fn:
            prepare_anatomical(self.config, "01", "01", self.t1_path, p3_override=override_p3)
        self.assertEqual(create_fn.call_args.kwargs["p3"], override_p3)

    def test_raises_when_p3_missing(self):
        self.config.registration_t1_target = "brain-csf"
        with self._layout(raw_t1=self.tmp / "raw.nii.gz", p3=None):
            with self.assertRaisesRegex(FileNotFoundError, "Missing p3 CSF map"):
                prepare_anatomical(self.config, "01", "01", self.t1_path)

    def test_raises_when_raw_t1_missing(self):
        self.config.registration_t1_target = "brain-csf"
        with self._layout(raw_t1=None, p3=self.tmp / "p3.nii.gz"):
            with self.assertRaisesRegex(FileNotFoundError, "Missing raw T1w acquisition required for brain-csf"):
                prepare_anatomical(self.config, "01", "01", self.t1_path)


class UnsupportedTargetTests(PrepareAnatomicalFixture):
    def test_unsupported_target_raises(self):
        self.config.registration_t1_target = "bogus"
        with self._layout():
            with self.assertRaisesRegex(ValueError, "Unsupported registration target"):
                prepare_anatomical(self.config, "01", "01", self.t1_path)


class CreateBrainCsfT1Fixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.affine = np.eye(4)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _save(self, name: str, data: np.ndarray, affine=None) -> Path:
        path = self.tmp / name
        nib.save(nib.Nifti1Image(data.astype(np.float32), affine if affine is not None else self.affine), path)
        return path


class CreateBrainCsfT1ValidationTests(CreateBrainCsfT1Fixture):
    def test_raises_on_shape_mismatch(self):
        skull = self._save("skull.nii.gz", np.ones((5, 5, 5)))
        raw = self._save("raw.nii.gz", np.ones((6, 6, 6)))
        p3 = self._save("p3.nii.gz", np.ones((5, 5, 5)))
        with self.assertRaisesRegex(ValueError, "different shapes"):
            create_brain_csf_t1(skull, raw, p3, self.tmp / "out.nii.gz", self.tmp / "out_mask.nii.gz")

    def test_raises_on_affine_mismatch(self):
        skull = self._save("skull.nii.gz", np.ones((5, 5, 5)))
        raw = self._save("raw.nii.gz", np.ones((5, 5, 5)), affine=np.diag([2.0, 2.0, 2.0, 1.0]))
        p3 = self._save("p3.nii.gz", np.ones((5, 5, 5)))
        with self.assertRaisesRegex(ValueError, "same affine"):
            create_brain_csf_t1(skull, raw, p3, self.tmp / "out.nii.gz", self.tmp / "out_mask.nii.gz")


class CreateBrainCsfT1ComputeTests(CreateBrainCsfT1Fixture):
    def test_adds_csf_voxels_outside_brain_mask(self):
        skull = np.zeros((5, 5, 5))
        skull[2, 2, 2] = 10.0  # the only "brain" voxel
        raw = np.full((5, 5, 5), 3.0)
        p3 = np.zeros((5, 5, 5))
        p3[2, 2, 3] = 0.99  # a CSF voxel adjacent to the brain, above threshold

        skull_path = self._save("skull.nii.gz", skull)
        raw_path = self._save("raw.nii.gz", raw)
        p3_path = self._save("p3.nii.gz", p3)
        out_t1 = self.tmp / "out.nii.gz"
        out_mask = self.tmp / "out_mask.nii.gz"

        create_brain_csf_t1(skull_path, raw_path, p3_path, out_t1, out_mask, threshold=0.95)

        result = nib.load(str(out_t1)).get_fdata()
        mask = nib.load(str(out_mask)).get_fdata()
        # skull(0) + raw(3.0) at the CSF voxel.
        self.assertAlmostEqual(result[2, 2, 3], 3.0, places=4)
        self.assertEqual(mask[2, 2, 3], 1)
        # The original brain voxel is untouched.
        self.assertAlmostEqual(result[2, 2, 2], 10.0, places=4)
        # A voxel with high p3 but not adjacent/relevant stays untouched (still 0, no CSF criterion met elsewhere).
        self.assertAlmostEqual(result[0, 0, 0], 0.0, places=4)

    def test_voxels_below_threshold_are_not_added(self):
        skull = np.zeros((4, 4, 4))
        raw = np.full((4, 4, 4), 5.0)
        p3 = np.zeros((4, 4, 4))
        p3[1, 1, 1] = 0.5  # below default threshold 0.95

        skull_path = self._save("skull.nii.gz", skull)
        raw_path = self._save("raw.nii.gz", raw)
        p3_path = self._save("p3.nii.gz", p3)
        out_t1 = self.tmp / "out.nii.gz"

        create_brain_csf_t1(skull_path, raw_path, p3_path, out_t1, self.tmp / "out_mask.nii.gz")

        result = nib.load(str(out_t1)).get_fdata()
        self.assertAlmostEqual(result[1, 1, 1], 0.0, places=4)

    def test_cached_output_is_reused_without_recomputation(self):
        skull = np.ones((3, 3, 3))
        skull_path = self._save("skull.nii.gz", skull)
        raw_path = self._save("raw.nii.gz", skull)
        p3_path = self._save("p3.nii.gz", np.zeros((3, 3, 3)))
        out_t1 = self.tmp / "out.nii.gz"
        out_mask = self.tmp / "out_mask.nii.gz"
        out_t1.touch()
        out_mask.touch()

        result_t1, result_mask = create_brain_csf_t1(skull_path, raw_path, p3_path, out_t1, out_mask, overwrite=False)

        self.assertEqual(result_t1, out_t1)
        self.assertEqual(result_mask, out_mask)
        self.assertEqual(out_t1.stat().st_size, 0)  # never rewritten


if __name__ == "__main__":
    unittest.main()

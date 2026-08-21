"""Tests for tissue/psf.py's orchestration layer. The numerical kernel
functions (hamming_sinc_psf_kernel, psf_axes, convolve_with_psf[_separable])
are already covered by test_psf.py; these target resample_tissue_to_mrsi_psf
and _blurred_scratch_path, which that file doesn't touch.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.tissue.psf import _blurred_scratch_path, resample_tissue_to_mrsi_psf


class BlurredScratchPathTests(unittest.TestCase):
    def test_includes_session_subdir_when_session_given(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SimpleNamespace(work_dir=Path(tmpdir))
            path = _blurred_scratch_path(config, "01", "01", "GM")
        self.assertIn("ses-01", str(path))
        self.assertIn("sub-01_label-GM_desc-psfblurredT1w_probseg.nii.gz", path.name)
        self.assertTrue(path.parent.is_dir())  # created eagerly

    def test_uses_ses_none_placeholder_when_session_absent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SimpleNamespace(work_dir=Path(tmpdir))
            path = _blurred_scratch_path(config, "01", None, "WM")
        self.assertIn("ses-none", str(path))


class ResampleTissueToMrsiPsfFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.mrsi_reference = self.tmp / "mrsi_ref.nii.gz"
        nib.save(nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.float32), np.eye(4)), self.mrsi_reference)
        self.tissue_path = self.tmp / "gm.nii.gz"
        nib.save(nib.Nifti1Image(np.ones((8, 8, 8), dtype=np.float32), np.eye(4)), self.tissue_path)
        self.config = SimpleNamespace(
            derivative_dir=self.tmp / "derivatives",
            work_dir=self.tmp / "work",
            overwrite_seg=False,
            overwrite=False,
            nthreads=4,
        )

    def tearDown(self):
        self._tmpdir.cleanup()


class CachedOutputTests(ResampleTissueToMrsiPsfFixture):
    def test_existing_target_is_reused_without_recomputation(self):
        target = self.tmp / "cached_gm_probseg.nii.gz"
        target.touch()
        with patch("mrsiprep.tissue.psf.mrsi_derivative", return_value=target), patch(
            "mrsiprep.tissue.psf.load_3d_data"
        ) as load_3d_data:
            result = resample_tissue_to_mrsi_psf(
                self.config, "01", "01", {"GM": self.tissue_path}, self.mrsi_reference, ["transform.mat"]
            )
        load_3d_data.assert_not_called()
        self.assertEqual(result, {"GM": target})

    def test_overwrite_forces_recomputation(self):
        target = self.tmp / "cached_gm_probseg.nii.gz"
        target.touch()
        self.config.overwrite = True
        with patch("mrsiprep.tissue.psf.mrsi_derivative", return_value=target), patch(
            "mrsiprep.tissue.psf.apply_image_transform", return_value=target
        ) as apply_transform:
            resample_tissue_to_mrsi_psf(self.config, "01", "01", {"GM": self.tissue_path}, self.mrsi_reference, ["transform.mat"])
        apply_transform.assert_called_once()


class ComputePathTests(ResampleTissueToMrsiPsfFixture):
    def test_blurs_resamples_and_returns_transformed_path_per_label(self):
        target_gm = self.tmp / "out_gm.nii.gz"
        target_wm = self.tmp / "out_wm.nii.gz"
        tissue_t1 = {"GM": self.tissue_path, "WM": self.tissue_path}

        with patch("mrsiprep.tissue.psf.mrsi_derivative", side_effect=[target_gm, target_wm]), patch(
            "mrsiprep.tissue.psf.apply_image_transform", side_effect=lambda *a, **k: a[3]
        ) as apply_transform:
            result = resample_tissue_to_mrsi_psf(
                self.config, "01", "01", tissue_t1, self.mrsi_reference, ["transform.mat"], truncation_radius=1.0
            )

        self.assertEqual(result, {"GM": target_gm, "WM": target_wm})
        self.assertEqual(apply_transform.call_count, 2)
        for call in apply_transform.call_args_list:
            self.assertEqual(call[0][2], ["transform.mat"])
            self.assertEqual(call.kwargs["interpolation"], "linear")
            self.assertEqual(call.kwargs["threads"], 4)

    def test_blurred_output_is_clipped_to_nonnegative_before_saving(self):
        # A tissue map with a large negative artifact must not propagate a
        # negative "probability" into the saved intermediate.
        signed_tissue = self.tmp / "signed.nii.gz"
        nib.save(nib.Nifti1Image(np.full((8, 8, 8), -5.0, dtype=np.float32), np.eye(4)), signed_tissue)
        target = self.tmp / "out.nii.gz"
        captured = {}

        def fake_save_nifti(data, reference, out_path, dtype=None):
            captured["data"] = data
            return out_path

        with patch("mrsiprep.tissue.psf.mrsi_derivative", return_value=target), patch(
            "mrsiprep.tissue.psf.save_nifti", side_effect=fake_save_nifti
        ), patch("mrsiprep.tissue.psf.apply_image_transform", return_value=target):
            resample_tissue_to_mrsi_psf(self.config, "01", "01", {"GM": signed_tissue}, self.mrsi_reference, ["transform.mat"])

        self.assertTrue(np.all(captured["data"] >= 0.0))


if __name__ == "__main__":
    unittest.main()

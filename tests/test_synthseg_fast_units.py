"""Tests for tissue/synthseg_fast.py beyond what test_synthseg_fast.py
already covers (_synthseg_command, _synthseg_csf_ventricle_mask,
_synthseg_brain_mask, _write_masked_t1, _apply_synthseg_csf_tissue_correction,
_synthseg_env). Targets the path-naming helpers, find_freesurfer_tool's
resolution order, _load_labels, _run_or_load_synthseg's cache/resample
logic, and segment_t1_synthseg_fast's orchestration.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.io.naming import anat_derivative
from mrsiprep.tissue.synthseg_fast import (
    _load_labels,
    _run_or_load_synthseg,
    find_freesurfer_tool,
    segment_t1_synthseg_fast,
    synthseg_fast_brain_mask_path,
    synthseg_fast_brain_path,
    synthseg_fast_csf_probseg_path,
    synthseg_fast_input_path,
    synthseg_native_labels_path,
    synthseg_work_dir,
)


class PathHelperTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(derivative_dir=Path("/deriv"), work_dir=Path("/work"), synthseg_mode="robust")

    def test_csf_probseg_path(self):
        path = synthseg_fast_csf_probseg_path(self.config, "01", "01")
        self.assertIn("label-CSF", path.name)
        self.assertIn("probseg", path.name)

    def test_brain_and_mask_paths_share_desc_but_differ_in_suffix(self):
        brain = synthseg_fast_brain_path(self.config, "01", "01")
        mask = synthseg_fast_brain_mask_path(self.config, "01", "01")
        self.assertIn("synthsegBrain", brain.name)
        self.assertIn("synthsegBrain", mask.name)
        self.assertIn("mask", mask.name)
        self.assertNotEqual(brain, mask)

    def test_native_labels_path_encodes_synthseg_mode(self):
        path = synthseg_native_labels_path(self.config, "01", "01")
        self.assertIn("synthsegParcRobust", path.name)

    def test_native_labels_path_defaults_mode_when_absent_from_config(self):
        config = SimpleNamespace(derivative_dir=Path("/deriv"))
        path = synthseg_native_labels_path(config, "01", "01")
        self.assertIn("synthsegParcFast", path.name)

    def test_work_dir_includes_session(self):
        wd = synthseg_work_dir(self.config, "01", "01")
        self.assertIn("sub-01", str(wd))
        self.assertIn("ses-01", str(wd))
        self.assertIn("synthseg_fast", str(wd))

    def test_work_dir_uses_ses_none_placeholder_without_session(self):
        wd = synthseg_work_dir(self.config, "01", None)
        self.assertIn("ses-none", str(wd))

    def test_fast_input_path_distinct_from_brain_path(self):
        self.assertNotEqual(synthseg_fast_input_path(self.config, "01", "01"), synthseg_fast_brain_path(self.config, "01", "01"))


class FindFreesurferToolTests(unittest.TestCase):
    def test_found_on_path_takes_priority(self):
        with patch("mrsiprep.tissue.synthseg_fast.shutil.which", return_value="/usr/bin/mri_synthseg"):
            self.assertEqual(find_freesurfer_tool("mri_synthseg"), "/usr/bin/mri_synthseg")

    def test_found_directly_under_freesurfer_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs_home = Path(tmpdir)
            tool_path = fs_home / "bin" / "mri_synthseg"
            tool_path.parent.mkdir(parents=True)
            tool_path.touch()
            with patch("mrsiprep.tissue.synthseg_fast.shutil.which", return_value=None), patch.dict(
                "os.environ", {"FREESURFER_HOME": str(fs_home)}, clear=True
            ):
                self.assertEqual(find_freesurfer_tool("mri_synthseg"), str(tool_path))

    def test_found_under_versioned_freesurfer_home_subdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs_home = Path(tmpdir)
            tool_path = fs_home / "freesurfer-7.4.1" / "bin" / "mri_synthseg"
            tool_path.parent.mkdir(parents=True)
            tool_path.touch()
            with patch("mrsiprep.tissue.synthseg_fast.shutil.which", return_value=None), patch.dict(
                "os.environ", {"FREESURFER_HOME": str(fs_home)}, clear=True
            ):
                self.assertEqual(find_freesurfer_tool("mri_synthseg"), str(tool_path))

    def test_raises_with_informative_message_when_not_found_anywhere(self):
        with patch("mrsiprep.tissue.synthseg_fast.shutil.which", return_value=None), patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(FileNotFoundError, "mri_synthseg was not found"):
                find_freesurfer_tool("mri_synthseg")


class LoadLabelsTests(unittest.TestCase):
    def test_rounds_and_casts_to_uint16(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "labels.nii.gz"
            data = np.array([[[1.4, 2.6, 43.0]]], dtype=np.float32)
            nib.save(nib.Nifti1Image(data, np.eye(4)), path)
            labels = _load_labels(path)
        self.assertEqual(labels.dtype, np.uint16)
        np.testing.assert_array_equal(labels.squeeze(), [1, 3, 43])


class RunOrLoadSynthsegFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.t1_path = self.tmp / "t1.nii.gz"
        nib.save(nib.Nifti1Image(np.ones((6, 6, 6), dtype=np.float32), np.eye(4)), self.t1_path)
        self.work_dir = self.tmp / "work"
        self.work_dir.mkdir()
        self.config = SimpleNamespace(
            derivative_dir=self.tmp / "derivatives",
            work_dir=self.work_dir,
            synthseg_mode="fast",
            overwrite_seg=False,
            overwrite=False,
            verbose=0,
            nthreads=2,
        )

    def tearDown(self):
        self._tmpdir.cleanup()


class RunOrLoadSynthsegCacheTests(RunOrLoadSynthsegFixture):
    def test_reuses_cached_native_labels_without_running_synthseg(self):
        native_labels = synthseg_native_labels_path(self.config, "01", "01")
        native_labels.parent.mkdir(parents=True, exist_ok=True)
        nib.save(nib.Nifti1Image(np.full((6, 6, 6), 5.0, dtype=np.float32), np.eye(4)), native_labels)

        with patch("mrsiprep.tissue.synthseg_fast.run_checked") as run_checked:
            labels = _run_or_load_synthseg(self.config, self.t1_path, self.work_dir, "01", "01")

        run_checked.assert_not_called()
        self.assertTrue(np.all(labels == 5))


class RunOrLoadSynthsegComputeTests(RunOrLoadSynthsegFixture):
    def test_runs_synthseg_and_caches_result(self):
        mode = self.config.synthseg_mode
        synthseg_out = self.work_dir / f"synthseg_parc-{mode}_labels.nii.gz"

        def fake_run_checked(cmd, **_kwargs):
            nib.save(nib.Nifti1Image(np.full((6, 6, 6), 7.0, dtype=np.float32), np.eye(4)), synthseg_out)

        with patch("mrsiprep.tissue.synthseg_fast.run_checked", side_effect=fake_run_checked) as run_checked, patch(
            "mrsiprep.tissue.synthseg_fast._find_mri_synthseg", return_value="/usr/local/freesurfer/bin/mri_synthseg"
        ):
            labels = _run_or_load_synthseg(self.config, self.t1_path, self.work_dir, "01", "01")

        run_checked.assert_called_once()
        self.assertTrue(np.all(labels == 7))
        native_labels = synthseg_native_labels_path(self.config, "01", "01")
        self.assertTrue(native_labels.exists())  # cached for next time

    def test_resamples_when_synthseg_output_grid_differs_from_t1(self):
        mode = self.config.synthseg_mode
        synthseg_out = self.work_dir / f"synthseg_parc-{mode}_labels.nii.gz"

        def fake_run_checked(cmd, **_kwargs):
            # A different (coarser) grid than the 6x6x6 T1 -- must be resampled onto it.
            nib.save(nib.Nifti1Image(np.full((3, 3, 3), 9.0, dtype=np.float32), np.diag([2.0, 2.0, 2.0, 1.0])), synthseg_out)

        with patch("mrsiprep.tissue.synthseg_fast.run_checked", side_effect=fake_run_checked), patch(
            "mrsiprep.tissue.synthseg_fast._find_mri_synthseg", return_value="/usr/local/freesurfer/bin/mri_synthseg"
        ):
            labels = _run_or_load_synthseg(self.config, self.t1_path, self.work_dir, "01", "01")

        self.assertEqual(labels.shape, (6, 6, 6))  # resampled onto the T1 grid


class SegmentT1SynthsegFastTests(RunOrLoadSynthsegFixture):
    def test_returns_cached_outputs_without_recomputation(self):
        outputs = {
            label: anat_derivative(self.config.derivative_dir, "01", "01", space="T1w", label=label, suffix_override="probseg")
            for label in ("GM", "WM", "CSF")
        }
        brain_out = synthseg_fast_brain_path(self.config, "01", "01")
        mask_out = synthseg_fast_brain_mask_path(self.config, "01", "01")
        for path in [*outputs.values(), brain_out, mask_out]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

        with patch("mrsiprep.tissue.synthseg_fast._run_or_load_synthseg") as run_or_load:
            result = segment_t1_synthseg_fast(self.config, "01", "01", self.t1_path)

        run_or_load.assert_not_called()
        self.assertEqual(result, outputs)

    def test_full_pipeline_wires_synthseg_fast_and_correction_together(self):
        labels = np.zeros((6, 6, 6), dtype=np.uint16)
        labels[1:5, 1:5, 1:5] = 2  # arbitrary non-background/non-CSF label

        fast_sources = {}
        for label, source_val in (("CSF", 0.1), ("GM", 0.6), ("WM", 0.3)):
            path = self.tmp / f"fast_{label}.nii.gz"
            nib.save(nib.Nifti1Image(np.full((6, 6, 6), source_val, dtype=np.float32), np.eye(4)), path)
            fast_sources[label] = path

        with patch("mrsiprep.tissue.synthseg_fast._run_or_load_synthseg", return_value=labels), patch(
            "mrsiprep.tissue.synthseg_fast.run_fast", return_value=fast_sources
        ) as run_fast_mock:
            result = segment_t1_synthseg_fast(self.config, "01", "01", self.t1_path)

        run_fast_mock.assert_called_once()
        for label in ("GM", "WM", "CSF"):
            self.assertIn(label, result)
            self.assertTrue(result[label].exists())
        # Inside the labeled region (label=2, not CSF/ventricle), values should
        # survive uncorrected: GM=0.6.
        gm_data = nib.load(str(result["GM"])).get_fdata()
        self.assertAlmostEqual(float(gm_data[2, 2, 2]), 0.6, places=4)


if __name__ == "__main__":
    unittest.main()

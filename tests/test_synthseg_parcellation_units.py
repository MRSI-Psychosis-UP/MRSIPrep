"""Tests for parcellation/synthseg.py -- previously entirely untested."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np
import pandas as pd

from mrsiprep.io.naming import parcellation_derivative
from mrsiprep.parcellation.synthseg import _read_freesurfer_lut, _write_labels, run_synthseg_parcellation


class RunSynthsegParcellationFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.config = SimpleNamespace(
            derivative_dir=self.tmp / "derivatives",
            synthseg_mode="fast",
            overwrite=False,
            nthreads=2,
        )
        self.raw_t1 = self.tmp / "t1.nii.gz"
        nib.save(nib.Nifti1Image(np.ones((1, 1, 4), dtype=np.float32), np.eye(4)), self.raw_t1)
        self.mrsi_reference = self.tmp / "mrsi_ref.nii.gz"
        self.t1_to_mrsi = [Path("transform.mat")]

    def tearDown(self):
        self._tmpdir.cleanup()


class RunSynthsegParcellationComputeTests(RunSynthsegParcellationFixture):
    def test_saves_filtered_atlas_and_writes_labels_when_not_cached(self):
        # Shape matches self.raw_t1 (1,1,4): WM(2), GM(3), a ventricle label
        # (4, must be zeroed), and the outer-CSF label (24, also zeroed).
        labels = np.array([[[2, 3, 4, 24]]], dtype=np.int32)

        with patch("mrsiprep.parcellation.synthseg.run_or_load_synthseg_labels", return_value=labels), patch(
            "mrsiprep.parcellation.synthseg.apply_image_transform"
        ) as apply_transform_mock, patch(
            "mrsiprep.parcellation.synthseg._write_labels", return_value=Path("labels.tsv")
        ) as write_labels_mock:
            result = run_synthseg_parcellation(self.config, "01", "01", self.raw_t1, self.mrsi_reference, self.t1_to_mrsi)

        self.assertTrue(result.atlas_t1.exists())
        saved = nib.load(str(result.atlas_t1)).get_fdata()
        np.testing.assert_array_equal(saved[0, 0, :], [2, 3, 0, 0])  # ventricle/outer-CSF filtered out

        apply_transform_mock.assert_called_once_with(
            self.mrsi_reference, result.atlas_t1, self.t1_to_mrsi, result.atlas_mrsi, interpolation="genericLabel", threads=2
        )
        write_labels_mock.assert_called_once()
        indices_arg, labels_out_arg = write_labels_mock.call_args[0]
        np.testing.assert_array_equal(sorted(indices_arg), [2, 3])
        self.assertEqual(labels_out_arg, result.labels)

        self.assertEqual(result.mode, "synthseg")
        self.assertEqual(result.atlas_name, "synthseg")
        self.assertIn("fastGMWM", str(result.atlas_t1))

    def test_skips_recompute_when_both_outputs_already_cached(self):
        mode = self.config.synthseg_mode
        atlas_t1 = parcellation_derivative(self.config.derivative_dir, "01", "01", space="T1w", atlas="synthseg", desc=f"{mode}GMWM")
        atlas_mrsi = parcellation_derivative(
            self.config.derivative_dir, "01", "01", space="MRSI", atlas="synthseg", desc=f"{mode}GMWM"
        )
        atlas_t1.parent.mkdir(parents=True, exist_ok=True)
        atlas_t1.touch()
        atlas_mrsi.parent.mkdir(parents=True, exist_ok=True)
        atlas_mrsi.touch()

        labels = np.array([[[2, 3]]], dtype=np.int32)
        with patch("mrsiprep.parcellation.synthseg.run_or_load_synthseg_labels", return_value=labels), patch(
            "mrsiprep.parcellation.synthseg.apply_image_transform"
        ) as apply_transform_mock, patch("mrsiprep.parcellation.synthseg._write_labels", return_value=Path("labels.tsv")):
            run_synthseg_parcellation(self.config, "01", "01", self.raw_t1, self.mrsi_reference, self.t1_to_mrsi)

        apply_transform_mock.assert_not_called()
        self.assertEqual(atlas_t1.stat().st_size, 0)  # never rewritten

    def test_overwrite_forces_recompute_even_when_cached(self):
        mode = self.config.synthseg_mode
        atlas_t1 = parcellation_derivative(self.config.derivative_dir, "01", "01", space="T1w", atlas="synthseg", desc=f"{mode}GMWM")
        atlas_mrsi = parcellation_derivative(
            self.config.derivative_dir, "01", "01", space="MRSI", atlas="synthseg", desc=f"{mode}GMWM"
        )
        atlas_t1.parent.mkdir(parents=True, exist_ok=True)
        atlas_t1.touch()
        atlas_mrsi.parent.mkdir(parents=True, exist_ok=True)
        atlas_mrsi.touch()
        self.config.overwrite = True

        labels = np.array([[[2, 3]]], dtype=np.int32)
        with patch("mrsiprep.parcellation.synthseg.run_or_load_synthseg_labels", return_value=labels), patch(
            "mrsiprep.parcellation.synthseg.apply_image_transform"
        ) as apply_transform_mock, patch("mrsiprep.parcellation.synthseg._write_labels", return_value=Path("labels.tsv")):
            run_synthseg_parcellation(self.config, "01", "01", self.raw_t1, self.mrsi_reference, self.t1_to_mrsi)

        apply_transform_mock.assert_called_once()
        self.assertGreater(atlas_t1.stat().st_size, 0)  # rewritten with real nifti content


class WriteLabelsTests(unittest.TestCase):
    def test_uses_freesurfer_lut_names_and_colors_when_available(self):
        with tempfile.TemporaryDirectory() as fs_home, tempfile.TemporaryDirectory() as outdir:
            lut_path = Path(fs_home) / "FreeSurferColorLUT.txt"
            lut_path.write_text(
                "2  Left-Cerebral-White-Matter  245 245 245 0\n" "3  Left-Cerebral-Cortex  205 62 78 0\n"
            )
            out_path = Path(outdir) / "labels.tsv"
            with patch.dict(os.environ, {"FREESURFER_HOME": fs_home}):
                result = _write_labels(np.array([2, 3]), out_path)
            df = pd.read_csv(result, sep="\t")

        self.assertEqual(list(df["parcel_id"]), [2, 3])
        self.assertEqual(list(df["parcel_name"]), ["Left-Cerebral-White-Matter", "Left-Cerebral-Cortex"])
        self.assertEqual(list(df["color"]), ["#f5f5f5", "#cd3e4e"])
        self.assertEqual(list(df["hemisphere"]), ["L", "L"])

    def test_unknown_parcel_id_falls_back_to_default_name_and_gray_color(self):
        with tempfile.TemporaryDirectory() as fs_home, tempfile.TemporaryDirectory() as outdir:
            # No FreeSurferColorLUT.txt written -> _read_freesurfer_lut() returns {}.
            out_path = Path(outdir) / "labels.tsv"
            with patch.dict(os.environ, {"FREESURFER_HOME": fs_home}):
                result = _write_labels(np.array([999]), out_path)
            df = pd.read_csv(result, sep="\t")

        self.assertEqual(df["parcel_name"][0], "SynthSeg-999")
        self.assertEqual(df["color"][0], "#808080")
        self.assertEqual(df["hemisphere"][0], "NA")

    def test_creates_missing_parent_directory(self):
        with tempfile.TemporaryDirectory() as fs_home, tempfile.TemporaryDirectory() as outdir:
            out_path = Path(outdir) / "nested" / "labels.tsv"
            with patch.dict(os.environ, {"FREESURFER_HOME": fs_home}):
                _write_labels(np.array([2]), out_path)
            self.assertTrue(out_path.exists())


class ReadFreesurferLutTests(unittest.TestCase):
    def test_returns_empty_dict_when_lut_file_missing(self):
        with tempfile.TemporaryDirectory() as fs_home:
            with patch.dict(os.environ, {"FREESURFER_HOME": fs_home}):
                self.assertEqual(_read_freesurfer_lut(), {})

    def test_parses_valid_lines_and_skips_malformed_ones(self):
        with tempfile.TemporaryDirectory() as fs_home:
            lut_path = Path(fs_home) / "FreeSurferColorLUT.txt"
            lut_path.write_text(
                "# too few fields, skipped\n"
                "2  Left-Cerebral-White-Matter  245 245 245 0\n"
                "notanumber  Foo  1 2 3 0\n"  # first field not a digit -> skipped
                "5  Bad-Color  notanumber 2 3 0\n"  # non-numeric color field -> skipped
            )
            with patch.dict(os.environ, {"FREESURFER_HOME": fs_home}):
                lut = _read_freesurfer_lut()
        self.assertEqual(lut, {2: ("Left-Cerebral-White-Matter", "#f5f5f5")})


if __name__ == "__main__":
    unittest.main()

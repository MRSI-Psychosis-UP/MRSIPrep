import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nibabel as nib
import numpy as np
import pandas as pd

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.reports.leakage_qc import write_signal_leakage_qc


def _make_config(tmp_path: Path) -> MRSIPrepConfig:
    return MRSIPrepConfig(
        tmp_path / "bids",
        tmp_path / "derivatives",
        "participant",
        participant_label=["S001"],
        session_label=["V1"],
        metabolites=["CrPCr"],
        ref_met="CrPCr",
    )


def _save_volume(path: Path, data: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data.astype("float32"), np.eye(4)), path)
    return path


class SignalLeakageQCT1SpaceTests(unittest.TestCase):
    def test_all_signal_inside_brain_mask_gives_zero_leakage(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            brain_mask = _save_volume(tmp_path / "brain.nii.gz", np.ones((4, 4, 4)))
            signal = _save_volume(tmp_path / "crpcr.nii.gz", np.full((4, 4, 4), 5.0))
            out = write_signal_leakage_qc(config, "S001", "V1", {"T1w": {"CrPCr": signal}}, brain_mask)
            self.assertIsNotNone(out)
            self.assertTrue(out.exists())
            df = pd.read_csv(out, sep="\t")
            self.assertEqual(len(df), 1)
            row = df.iloc[0]
            self.assertEqual(row["space"], "T1w")
            self.assertEqual(row["metabolite"], "CrPCr")
            self.assertAlmostEqual(row["leakage_fraction"], 0.0)
            self.assertAlmostEqual(row["leakage_percent"], 0.0)
            self.assertEqual(row["n_quality_voxels"], 64)

    def test_signal_outside_mask_is_weighted_by_magnitude(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            mask_data = np.zeros((2, 2, 2))
            mask_data[0, 0, 0] = 1  # only this voxel is "inside" the brain
            brain_mask = _save_volume(tmp_path / "brain.nii.gz", mask_data)
            signal_data = np.zeros((2, 2, 2))
            signal_data[0, 0, 0] = 9.0  # inside
            signal_data[1, 1, 1] = 1.0  # outside
            signal = _save_volume(tmp_path / "crpcr.nii.gz", signal_data)
            out = write_signal_leakage_qc(config, "S001", "V1", {"T1w": {"CrPCr": signal}}, brain_mask)
            df = pd.read_csv(out, sep="\t")
            row = df.iloc[0]
            self.assertAlmostEqual(row["leakage_fraction"], 0.1)
            self.assertAlmostEqual(row["leakage_percent"], 10.0)

    def test_crlb_filters_low_quality_voxels(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            mask_data = np.zeros((2, 2, 2))
            mask_data[0, 0, 0] = 1
            brain_mask = _save_volume(tmp_path / "brain.nii.gz", mask_data)
            signal_data = np.full((2, 2, 2), np.nan)
            signal_data[0, 0, 0] = 9.0  # inside
            signal_data[1, 1, 1] = 1.0  # outside
            signal = _save_volume(tmp_path / "crpcr.nii.gz", signal_data)
            crlb_data = np.full((2, 2, 2), 1.0)
            crlb_data[0, 0, 0] = 999.0  # inside voxel fails CRLB
            crlb = _save_volume(tmp_path / "crlb.nii.gz", crlb_data)
            out = write_signal_leakage_qc(
                config, "S001", "V1", {"T1w": {"CrPCr": signal, "crlb-CrPCr": crlb}}, brain_mask
            )
            df = pd.read_csv(out, sep="\t")
            row = df.iloc[0]
            self.assertEqual(row["n_quality_voxels"], 1)
            self.assertAlmostEqual(row["leakage_fraction"], 1.0)

    def test_returns_none_without_reference_brain_mask_or_mni_maps(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            signal = _save_volume(tmp_path / "crpcr.nii.gz", np.ones((4, 4, 4)))
            self.assertIsNone(write_signal_leakage_qc(config, "S001", "V1", {"T1w": {"CrPCr": signal}}, None))

    def test_ignores_non_metabolite_quality_map_keys(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            brain_mask = _save_volume(tmp_path / "brain.nii.gz", np.ones((4, 4, 4)))
            signal = _save_volume(tmp_path / "crpcr.nii.gz", np.full((4, 4, 4), 5.0))
            snr = _save_volume(tmp_path / "snr.nii.gz", np.ones((4, 4, 4)))
            fwhm = _save_volume(tmp_path / "fwhm.nii.gz", np.ones((4, 4, 4)))
            out = write_signal_leakage_qc(
                config, "S001", "V1", {"T1w": {"CrPCr": signal, "snr": snr, "fwhm": fwhm}}, brain_mask
            )
            df = pd.read_csv(out, sep="\t")
            self.assertEqual(sorted(df["metabolite"]), ["CrPCr"])

    def test_no_transformed_spaces_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            self.assertIsNone(write_signal_leakage_qc(config, "S001", "V1", {}, None))
            self.assertIsNone(write_signal_leakage_qc(config, "S001", "V1", None, None))


class SignalLeakageQCMNISpaceTests(unittest.TestCase):
    def test_mni_space_leakage_uses_standard_brain_mask(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            # A generous, uniform-affine grid so the resampled nilearn MNI
            # brain mask lands mostly "inside" somewhere in the volume --
            # this test only needs *some* inside/outside contrast to exist,
            # not exact voxel positions.
            affine = np.diag([5.0, 5.0, 5.0, 1.0])
            affine[:3, 3] = [-90, -126, -72]
            shape = (36, 43, 36)
            signal_data = np.ones(shape, dtype="float32")
            signal_img = nib.Nifti1Image(signal_data, affine)
            signal_path = tmp_path / "crpcr_mni.nii.gz"
            nib.save(signal_img, signal_path)

            fake_mask = nib.Nifti1Image(np.ones(shape, dtype="float32"), affine)
            with mock.patch("mrsiprep.reports.leakage_qc.resample_from_to", return_value=fake_mask):
                out = write_signal_leakage_qc(
                    config, "S001", "V1", {"MNI152NLin2009cAsym": {"CrPCr": signal_path}}, None
                )
            self.assertIsNotNone(out)
            df = pd.read_csv(out, sep="\t")
            row = df.iloc[0]
            self.assertEqual(row["space"], "MNI152NLin2009cAsym")
            self.assertEqual(row["metabolite"], "CrPCr")
            self.assertAlmostEqual(row["leakage_fraction"], 0.0)


if __name__ == "__main__":
    unittest.main()

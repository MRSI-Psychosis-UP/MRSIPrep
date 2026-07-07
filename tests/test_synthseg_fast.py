import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.tissue.synthseg_fast import (
    CSF_VENTRICLE_LABELS,
    OUTER_CSF_LABEL,
    VENTRICLE_LABELS,
    _apply_synthseg_csf_tissue_correction,
    _synthseg_brain_mask,
    _synthseg_csf_ventricle_mask,
    _synthseg_env,
    _synthseg_command,
    _write_masked_t1,
)


class SynthSegFastTests(unittest.TestCase):
    def test_fast_parcellation_command_uses_threads_without_robust(self):
        config = type("Config", (), {"synthseg_mode": "fast", "nthreads": 8})()
        command = _synthseg_command(config, "mri_synthseg", Path("t1.nii.gz"), Path("labels.nii.gz"))
        self.assertIn("--parc", command)
        self.assertIn("--fast", command)
        self.assertIn("--cpu", command)
        self.assertNotIn("--robust", command)
        self.assertEqual(command[command.index("--threads") + 1], "8")

    def test_robust_parcellation_command_never_adds_fast(self):
        config = type("Config", (), {"synthseg_mode": "robust", "nthreads": 4})()
        command = _synthseg_command(config, "mri_synthseg", Path("t1.nii.gz"), Path("labels.nii.gz"))
        self.assertIn("--robust", command)
        self.assertNotIn("--fast", command)

    def test_synthseg_csf_ventricle_mask_includes_ventricles_and_csf(self):
        labels = np.zeros((4, 4, 4), dtype=np.uint8)
        for idx, value in enumerate(sorted(CSF_VENTRICLE_LABELS)):
            labels[idx % 4, idx // 4, 0] = value
        labels[3, 3, 3] = 3

        mask = _synthseg_csf_ventricle_mask(labels)

        self.assertEqual(int(np.count_nonzero(mask)), len(CSF_VENTRICLE_LABELS))
        self.assertFalse(bool(mask[3, 3, 3]))

    def test_synthseg_brain_mask_excludes_only_background(self):
        labels = np.array([0, OUTER_CSF_LABEL, 3, 2, *sorted(VENTRICLE_LABELS)], dtype=np.uint8)

        mask = _synthseg_brain_mask(labels)

        self.assertFalse(bool(mask[0]))
        self.assertTrue(np.all(mask[1:]))

    def test_write_masked_t1_uses_numpy_masking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data = np.arange(27, dtype=np.float32).reshape(3, 3, 3)
            mask = np.zeros((3, 3, 3), dtype=bool)
            mask[1, :, :] = True
            img = nib.Nifti1Image(data, np.eye(4))

            out = _write_masked_t1(img, mask, root / "masked.nii.gz")
            masked = nib.load(str(out)).get_fdata(dtype=np.float32)

            self.assertEqual(float(masked[0].sum()), 0.0)
            self.assertGreater(float(masked[1].sum()), 0.0)
            self.assertEqual(float(masked[2].sum()), 0.0)

    def test_synthseg_csf_tissue_correction_moves_gm_and_wm_to_csf_on_csf_and_ventricle_labels(self):
        labels = np.zeros((2, 2, 2), dtype=np.uint8)
        labels[0, 0, 0] = OUTER_CSF_LABEL
        labels[0, 0, 1] = OUTER_CSF_LABEL
        labels[0, 1, 0] = sorted(VENTRICLE_LABELS)[0]
        labels[1, 0, 0] = 3
        labels[1, 1, 1] = 2
        maps = {
            "GM": np.zeros((2, 2, 2), dtype=np.float32),
            "WM": np.zeros((2, 2, 2), dtype=np.float32),
            "CSF": np.zeros((2, 2, 2), dtype=np.float32),
        }
        maps["GM"][0, 1, 0] = 0.03
        maps["GM"][1, 0, 0] = 0.60
        maps["WM"][0, 0, 0] = 0.02
        maps["WM"][0, 0, 1] = 0.01
        maps["WM"][1, 1, 1] = 0.50

        corrected = _apply_synthseg_csf_tissue_correction(maps, labels)

        self.assertEqual(float(corrected["WM"][0, 0, 0]), 0.0)
        self.assertEqual(float(corrected["CSF"][0, 0, 0]), 1.0)
        self.assertEqual(float(corrected["GM"][0, 1, 0]), 0.0)
        self.assertEqual(float(corrected["CSF"][0, 1, 0]), 1.0)
        self.assertAlmostEqual(float(corrected["WM"][0, 0, 1]), 0.01)
        self.assertEqual(float(corrected["CSF"][0, 0, 1]), 0.0)
        self.assertAlmostEqual(float(corrected["GM"][1, 0, 0]), 0.60)
        self.assertEqual(float(corrected["WM"][1, 1, 1]), 0.50)

    def test_synthseg_correction_zeros_all_tissues_on_label0(self):
        labels = np.ones((2, 2, 2), dtype=np.uint8)
        labels[0, 0, 0] = 0
        maps = {
            "GM": np.full((2, 2, 2), 0.2, dtype=np.float32),
            "WM": np.full((2, 2, 2), 0.3, dtype=np.float32),
            "CSF": np.full((2, 2, 2), 0.4, dtype=np.float32),
        }

        corrected = _apply_synthseg_csf_tissue_correction(maps, labels)

        self.assertEqual(float(corrected["GM"][0, 0, 0]), 0.0)
        self.assertEqual(float(corrected["WM"][0, 0, 0]), 0.0)
        self.assertEqual(float(corrected["CSF"][0, 0, 0]), 0.0)
        self.assertAlmostEqual(float(corrected["GM"][1, 1, 1]), 0.2)
        self.assertAlmostEqual(float(corrected["WM"][1, 1, 1]), 0.3)
        self.assertAlmostEqual(float(corrected["CSF"][1, 1, 1]), 0.4)

    def test_synthseg_env_sets_matching_freesurfer_home_for_wrappers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs_home = Path(tmpdir) / "freesurfer"
            command = fs_home / "bin" / "mri_synthseg"
            script = fs_home / "python" / "scripts" / "mri_synthseg"
            command.parent.mkdir(parents=True)
            script.parent.mkdir(parents=True)
            command.touch()
            script.touch()

            env = _synthseg_env(str(command))

            self.assertEqual(env["FREESURFER_HOME"], str(fs_home))


if __name__ == "__main__":
    unittest.main()

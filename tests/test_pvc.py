import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.mrsi.pvc import PVCError, run_pvc


class PVCTests(unittest.TestCase):
    def test_run_pvc_creates_output_directory_before_petpvc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4))
            metabolite = root / "metabolite.nii.gz"
            brainmask = root / "brainmask.nii.gz"
            tissue = root / "tissue.nii.gz"
            nib.save(image, metabolite)
            nib.save(image, brainmask)
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2, 3), dtype=np.float32), np.eye(4)), tissue)
            config = SimpleNamespace(derivative_dir=root / "derivatives", overwrite=False, overwrite_pve=False)

            def fake_petpvc(command, **_kwargs):
                output = Path(command[command.index("-o") + 1])
                self.assertTrue(output.parent.is_dir())
                nib.save(image, output)
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("mrsiprep.mrsi.pvc.shutil.which", return_value="/usr/bin/petpvc"), patch(
                "mrsiprep.mrsi.pvc.run_checked", side_effect=fake_petpvc
            ):
                outputs = run_pvc(config, "S001", "V1", {"CrPCr": metabolite}, tissue, brainmask)

            self.assertTrue(outputs["CrPCr"].exists())

    def test_run_pvc_reports_petpvc_stderr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4))
            metabolite = root / "metabolite.nii.gz"
            brainmask = root / "brainmask.nii.gz"
            tissue = root / "tissue.nii.gz"
            nib.save(image, metabolite)
            nib.save(image, brainmask)
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2, 3), dtype=np.float32), np.eye(4)), tissue)
            config = SimpleNamespace(derivative_dir=root / "derivatives", overwrite=False, overwrite_pve=False)
            failure = subprocess.CompletedProcess(["petpvc"], 1, "", "cannot write output")

            with patch("mrsiprep.mrsi.pvc.shutil.which", return_value="/usr/bin/petpvc"), patch(
                "mrsiprep.mrsi.pvc.run_checked", return_value=failure
            ):
                with self.assertRaisesRegex(PVCError, "cannot write output"):
                    run_pvc(config, "S001", "V1", {"CrPCr": metabolite}, tissue, brainmask)


if __name__ == "__main__":
    unittest.main()

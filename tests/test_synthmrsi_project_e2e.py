"""Real end-to-end run of MRSIPrep against the public SynthMRSI-Project
fixture. Needs Docker and a downloaded/extracted copy of the dataset --
skipped by default in the normal test/coverage run, since neither is
available on the plain ubuntu-latest runner coverage.yml uses.

Since the pipeline runs inside the mrsiup/mrsiprep:cpu container's own
Python interpreter, this test cannot feed the host's `--cov=mrsiprep`
numbers -- its value is end-to-end regression/smoke confidence, not a raw
coverage-percentage gain.

Enable locally:
    MRSIPREP_E2E_DATA_DIR=/path/to/extracted/SynthMRSI-Project \
      pytest -m e2e_synthmrsi_project tests/test_synthmrsi_project_e2e.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_DATA_DIR_ENV = "MRSIPREP_E2E_DATA_DIR"
_SKIP_PULL_ENV = "MRSIPREP_E2E_SKIP_PULL"
_IMAGE = "mrsiup/mrsiprep:cpu"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@unittest.skipUnless(os.environ.get(_DATA_DIR_ENV), f"set {_DATA_DIR_ENV} to an extracted SynthMRSI-Project directory to run this test")
@unittest.skipUnless(_docker_available(), "docker is not available on PATH")
class SynthMRSIProjectE2ETests(unittest.TestCase):
    """pytest marker: e2e_synthmrsi_project (registered in pyproject.toml)."""

    def setUp(self):
        self.data_dir = Path(os.environ[_DATA_DIR_ENV]).resolve()
        if not self.data_dir.is_dir():
            self.skipTest(f"{_DATA_DIR_ENV} does not point at a directory: {self.data_dir}")
        fs_license = os.environ.get("FS_LICENSE")
        if not fs_license or not Path(fs_license).is_file():
            self.skipTest("FS_LICENSE must point at a valid FreeSurfer license file")
        self.fs_license = Path(fs_license).resolve()

        if os.environ.get(_SKIP_PULL_ENV) != "1":
            subprocess.run(["docker", "pull", _IMAGE], check=True)

        self.out_dir = Path(tempfile.mkdtemp(prefix="mrsiprep_e2e_out_"))
        self.addCleanup(shutil.rmtree, self.out_dir, ignore_errors=True)

    def test_two_subjects_run_end_to_end(self):
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{self.data_dir}:/data:ro",
            "-v", f"{self.out_dir}:/out",
            "-v", f"{self.fs_license}:/opt/freesurfer/license.txt:ro",
            "-e", "FS_LICENSE=/opt/freesurfer/license.txt",
            _IMAGE,
            "/data", "/out", "participant",
            "--participant-label", "01", "05",
            "--session-label", "01",
            "--mode", "mni-norm",
            "--t1", "acq-mprage_T1w",
            "--metabolites", "NAANAAG,GPCPCh,CrPCr,GluGln,Ins",
            "--ref-met", "CrPCr",
            "--nthreads", "4", "--nproc", "1", "--verbose", "1",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, msg=f"mrsiprep run failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

        for subject in ("01", "05"):
            subject_root = self.out_dir / "mrsiprep" / f"sub-{subject}" / "ses-01"
            self.assertTrue(subject_root.is_dir(), msg=f"no output directory for sub-{subject}: {subject_root}")

            qc_reports = list((subject_root / "reports" / "qc-reports").glob(f"sub-{subject}_ses-01_step-combined.html"))
            self.assertTrue(qc_reports, msg=f"no combined QC report for sub-{subject} under {subject_root}")
            self.assertGreater(qc_reports[0].stat().st_size, 1024, msg=f"QC report for sub-{subject} looks too small to be real")

            mni_maps = list((subject_root / "mrsi" / "mni").glob("*.nii.gz"))
            self.assertTrue(mni_maps, msg=f"no MNI-space metabolite maps for sub-{subject} under {subject_root}")


if __name__ == "__main__":
    unittest.main()

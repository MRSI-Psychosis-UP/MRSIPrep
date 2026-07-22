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

import pytest

_DATA_DIR_ENV = "MRSIPREP_E2E_DATA_DIR"
_SKIP_PULL_ENV = "MRSIPREP_E2E_SKIP_PULL"
_IMAGE = "mrsiup/mrsiprep:cpu"

pytestmark = pytest.mark.e2e_synthmrsi_project


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@unittest.skipUnless(os.environ.get(_DATA_DIR_ENV), f"set {_DATA_DIR_ENV} to an extracted SynthMRSI-Project directory to run this test")
@unittest.skipUnless(_docker_available(), "docker is not available on PATH")
class SynthMRSIProjectE2ETests(unittest.TestCase):

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

    def test_two_subjects_run_end_to_end_mni_norm(self):
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
            # --synthseg-mode fast, not the default "robust": SynthSeg-robust's
            # inference is memory-hungry enough to hit std::bad_alloc on
            # GitHub's standard 16GB-RAM runners (confirmed via a live CI
            # crash: "mri_synthseg exited with status -6 ... terminate
            # called after throwing an instance of 'std::bad_alloc'").
            "--synthseg-mode", "fast",
            # Self-managed 64-thread/128GB larger runner (mrsiprep_runner) --
            # 32 threads x 2 parallel subjects uses the full runner.
            "--nthreads", "32", "--nproc", "2", "--verbose", "1",
        ]
        # Stream output live (rather than capture_output=True, which buffers
        # everything silently until the process exits) so a hang is visible
        # in CI logs as it happens, not just as a wall of text after a
        # timeout finally kills it. A hard timeout bounds worst-case runtime
        # instead of relying on GitHub's own 6-hour job cap.
        lines: list[str] = []
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                lines.append(line)
            returncode = process.wait(timeout=1200)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            self.fail(f"mrsiprep run exceeded 1200s timeout without finishing. Output so far:\n{''.join(lines)}")
        self.assertEqual(returncode, 0, msg=f"mrsiprep run failed:\n{''.join(lines)}")

        for subject in ("01", "05"):
            subject_root = self.out_dir / "mrsiprep" / f"sub-{subject}" / "ses-01"
            self.assertTrue(subject_root.is_dir(), msg=f"no output directory for sub-{subject}: {subject_root}")

            qc_reports = list((subject_root / "reports" / "qc-reports").glob(f"sub-{subject}_ses-01_step-combined.html"))
            self.assertTrue(qc_reports, msg=f"no combined QC report for sub-{subject} under {subject_root}")
            self.assertGreater(qc_reports[0].stat().st_size, 1024, msg=f"QC report for sub-{subject} looks too small to be real")

            mni_maps = list((subject_root / "mrsi" / "mni").glob("*.nii.gz"))
            self.assertTrue(mni_maps, msg=f"no MNI-space metabolite maps for sub-{subject} under {subject_root}")

    def test_two_subjects_run_end_to_end_parc_con(self):
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
            "--mode", "parc-con",
            "--t1", "acq-mprage_T1w",
            "--metabolites", "NAANAAG,GPCPCh,CrPCr,GluGln,Ins",
            "--ref-met", "CrPCr",
            # Same rationale as the mni-norm test: keep SynthSeg-fast rather
            # than the memory-hungry default "robust" mode.
            "--synthseg-mode", "fast",
            # Self-managed 64-thread/128GB larger runner (mrsiprep_runner) --
            # 32 threads x 2 parallel subjects uses the full runner. Unlike
            # mni-norm, parc-con's default parcellation-mode is "chimera",
            # which runs FreeSurfer recon-all (documented 1-3h/subject) and
            # Chimera (10-20+min/subject) -- run in parallel across the 2
            # subjects, so wall time is bounded by one subject's worst case.
            "--nthreads", "32", "--nproc", "2", "--verbose", "1",
        ]
        lines: list[str] = []
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                lines.append(line)
            returncode = process.wait(timeout=14400)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            self.fail(f"mrsiprep run exceeded 14400s timeout without finishing. Output so far:\n{''.join(lines)}")
        self.assertEqual(returncode, 0, msg=f"mrsiprep run failed:\n{''.join(lines)}")

        for subject in ("01", "05"):
            subject_root = self.out_dir / "mrsiprep" / f"sub-{subject}" / "ses-01"
            self.assertTrue(subject_root.is_dir(), msg=f"no output directory for sub-{subject}: {subject_root}")

            qc_reports = list((subject_root / "reports" / "qc-reports").glob(f"sub-{subject}_ses-01_step-combined.html"))
            self.assertTrue(qc_reports, msg=f"no combined QC report for sub-{subject} under {subject_root}")
            self.assertGreater(qc_reports[0].stat().st_size, 1024, msg=f"QC report for sub-{subject} looks too small to be real")

            # parc-con is a documented superset of mni-norm's outputs.
            mni_maps = list((subject_root / "mrsi" / "mni").glob("*.nii.gz"))
            self.assertTrue(mni_maps, msg=f"no MNI-space metabolite maps for sub-{subject} under {subject_root}")

            # parc-con-specific: proves Chimera/FreeSurfer recon-all and PVC
            # actually ran, not just the mni-norm steps.
            parcel_profiles = list((subject_root / "mrsi" / "parcel").glob("*.npz"))
            self.assertTrue(parcel_profiles, msg=f"no parcel profile archive for sub-{subject} under {subject_root}")


if __name__ == "__main__":
    unittest.main()

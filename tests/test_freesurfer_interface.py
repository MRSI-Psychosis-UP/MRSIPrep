import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mrsiprep.interfaces.freesurfer import (
    FreeSurferError,
    check_license,
    freesurfer_subject_id,
    require_command,
    run_recon_all,
    subject_dir_valid,
)


class CheckLicenseTests(unittest.TestCase):
    def test_raises_when_no_candidate_exists(self):
        # No FS_LICENSE/FREESURFER_HOME set, and the hardcoded fallback
        # (/opt/freesurfer/license.txt) is not expected to exist in CI.
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(FreeSurferError, "FreeSurfer license not found"):
                check_license()

    def test_fs_license_env_var_takes_priority(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            license_path = Path(tmpdir) / "license.txt"
            license_path.touch()
            other = Path(tmpdir) / "freesurfer_home" / "license.txt"
            other.parent.mkdir()
            other.touch()
            with patch.dict("os.environ", {"FS_LICENSE": str(license_path), "FREESURFER_HOME": str(other.parent)}, clear=True):
                check_license()
                self.assertEqual(__import__("os").environ["FS_LICENSE"], str(license_path))

    def test_falls_back_to_freesurfer_home_when_fs_license_unset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs_home = Path(tmpdir)
            (fs_home / "license.txt").touch()
            with patch.dict("os.environ", {"FREESURFER_HOME": str(fs_home)}, clear=True):
                check_license()
                self.assertEqual(__import__("os").environ["FS_LICENSE"], str(fs_home / "license.txt"))


class RequireCommandTests(unittest.TestCase):
    def test_raises_when_not_on_path(self):
        with patch("mrsiprep.interfaces.freesurfer.shutil.which", return_value=None):
            with self.assertRaisesRegex(FreeSurferError, "recon-all"):
                require_command("recon-all")

    def test_returns_resolved_path(self):
        with patch("mrsiprep.interfaces.freesurfer.shutil.which", return_value="/usr/local/bin/recon-all"):
            self.assertEqual(require_command("recon-all"), "/usr/local/bin/recon-all")


class FreesurferSubjectIdTests(unittest.TestCase):
    def test_strips_nii_gz_and_final_bids_entity(self):
        self.assertEqual(freesurfer_subject_id("sub-01_ses-01_acq-mprage_T1w.nii.gz"), "sub-01_ses-01_acq-mprage")

    def test_strips_mgz_and_final_bids_entity(self):
        self.assertEqual(freesurfer_subject_id("sub-01_T1w.mgz"), "sub-01")

    def test_name_without_underscore_is_returned_unchanged(self):
        self.assertEqual(freesurfer_subject_id("T1w.nii.gz"), "T1w")

    def test_path_with_no_recognized_extension_uses_stem(self):
        self.assertEqual(freesurfer_subject_id("sub-01_T1w.nii"), "sub-01")


class SubjectDirValidTests(unittest.TestCase):
    def _make_valid_subject(self, root: Path, subject: str) -> None:
        for rel in ("mri/brain.mgz", "mri/aseg.mgz", "mri/orig.mgz", "surf/lh.white", "surf/rh.white", "surf/lh.pial", "surf/rh.pial"):
            path = root / subject / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def test_true_when_all_required_outputs_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_valid_subject(root, "sub-01")
            self.assertTrue(subject_dir_valid(root, "sub-01"))

    def test_false_when_one_required_output_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_valid_subject(root, "sub-01")
            (root / "sub-01" / "surf" / "rh.pial").unlink()
            self.assertFalse(subject_dir_valid(root, "sub-01"))

    def test_false_when_subject_dir_absent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse(subject_dir_valid(Path(tmpdir), "sub-nonexistent"))


class RunReconAllFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.t1 = self.tmp / "sub-01_T1w.nii.gz"
        self.t1.touch()
        self.fs_dir = self.tmp / "freesurfer"
        self._patches = [
            patch("mrsiprep.interfaces.freesurfer.require_command", return_value="/usr/local/bin/recon-all"),
            patch("mrsiprep.interfaces.freesurfer.check_license"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_valid_subject(self, subject: str) -> None:
        for rel in ("mri/brain.mgz", "mri/aseg.mgz", "mri/orig.mgz", "surf/lh.white", "surf/rh.white", "surf/lh.pial", "surf/rh.pial"):
            path = self.fs_dir / subject / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()


class ReuseExistingOutputTests(RunReconAllFixture):
    def test_valid_existing_output_is_reused_without_running_recon_all(self):
        self._make_valid_subject("sub-01")
        with patch("mrsiprep.interfaces.freesurfer.run_checked") as run_checked:
            result = run_recon_all(self.t1, self.fs_dir, "sub-01")
        run_checked.assert_not_called()
        self.assertEqual(result, self.fs_dir / "sub-01")


class FreshReconAllTests(RunReconAllFixture):
    def test_missing_subject_dir_runs_with_dash_i_import(self):
        def fake_run_checked(cmd, **_kwargs):
            self._make_valid_subject("sub-01")

        with patch("mrsiprep.interfaces.freesurfer.run_checked", side_effect=fake_run_checked) as run_checked:
            result = run_recon_all(self.t1, self.fs_dir, "sub-01")

        cmd = run_checked.call_args[0][0]
        self.assertIn("-i", cmd)
        self.assertIn(str(self.t1), cmd)
        self.assertEqual(result, self.fs_dir / "sub-01")

    def test_raises_when_outputs_still_missing_after_recon_all(self):
        with patch("mrsiprep.interfaces.freesurfer.run_checked"):
            with self.assertRaisesRegex(FreeSurferError, "required outputs are missing"):
                run_recon_all(self.t1, self.fs_dir, "sub-01")


class PartialReconAllResumeTests(RunReconAllFixture):
    def test_existing_but_invalid_subject_dir_resumes_without_dash_i(self):
        """A subject directory that exists but isn't yet complete (an
        interrupted prior run) must be resumed via `-s ... -all` without
        re-passing `-i`, since FreeSurfer already imported the T1 the first
        time and re-importing would conflict with the partial run."""
        (self.fs_dir / "sub-01" / "mri").mkdir(parents=True)
        (self.fs_dir / "sub-01" / "mri" / "orig.mgz").touch()

        def fake_run_checked(cmd, **_kwargs):
            self._make_valid_subject("sub-01")

        with patch("mrsiprep.interfaces.freesurfer.run_checked", side_effect=fake_run_checked) as run_checked:
            run_recon_all(self.t1, self.fs_dir, "sub-01")

        cmd = run_checked.call_args[0][0]
        self.assertNotIn("-i", cmd)
        self.assertIn("-s", cmd)


class ForceReconAllTests(RunReconAllFixture):
    def test_force_removes_existing_dir_and_reimports(self):
        self._make_valid_subject("sub-01")

        def fake_run_checked(cmd, **_kwargs):
            self._make_valid_subject("sub-01")

        with patch("mrsiprep.interfaces.freesurfer.run_checked", side_effect=fake_run_checked) as run_checked:
            run_recon_all(self.t1, self.fs_dir, "sub-01", force=True)

        cmd = run_checked.call_args[0][0]
        self.assertIn("-i", cmd)


if __name__ == "__main__":
    unittest.main()

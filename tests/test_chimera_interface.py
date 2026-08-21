import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mrsiprep.interfaces.chimera import ChimeraError, check_chimera, run_chimera


class CheckChimeraTests(unittest.TestCase):
    def test_raises_when_not_on_path(self):
        with patch("mrsiprep.interfaces.chimera.shutil.which", return_value=None):
            with self.assertRaisesRegex(ChimeraError, "Chimera command not found"):
                check_chimera()

    def test_no_op_when_found(self):
        with patch("mrsiprep.interfaces.chimera.shutil.which", return_value="/usr/local/bin/chimera"):
            check_chimera()  # must not raise


class RunChimeraFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.bids_dir = self.tmp / "bids"
        self.derivatives_dir = self.tmp / "derivatives"
        self.fs_subjects_dir = self.tmp / "freesurfer"
        self.t1_path = self.tmp / "sub-01_T1w.nii.gz"
        self.t1_path.touch()
        self._which_patch = patch("mrsiprep.interfaces.chimera.shutil.which", return_value="/usr/local/bin/chimera")
        self._which_patch.start()
        self.addCleanup(self._which_patch.stop)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _touch_output(self, subject: str, session: str | None, scheme: str, scale: int) -> Path:
        name = f"sub-{subject}"
        if session:
            name += f"_ses-{session}"
        name += f"_atlas-chimera{scheme}_scale-{scale}_dseg.nii.gz"
        out = self.derivatives_dir / "chimera" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.touch()
        return out


class SuccessfulRunTests(RunChimeraFixture):
    def test_returns_matching_output_and_forces_single_thread(self):
        expected = self._touch_output("01", "01", "LFMIHIFIFF", 3)

        with patch("mrsiprep.interfaces.chimera.run_checked") as run_checked:
            run_checked.return_value = MagicMock(stdout="")
            result = run_chimera(
                self.bids_dir, self.derivatives_dir, self.fs_subjects_dir, self.t1_path, "01", "01", "LFMIHIFIFF", 3, 2,
            )

        self.assertEqual(result, expected)
        cmd = run_checked.call_args[0][0]
        self.assertEqual(cmd[0], "chimera")
        # Regression: chimera's own --nthreads silently drops unfinished
        # work above 1 (unawaited ThreadPoolExecutor futures) -- must always
        # be forced to 1 regardless of caller parallelism.
        self.assertEqual(cmd[cmd.index("--nthreads") + 1], "1")

    def test_session_none_omits_ses_from_search_pattern(self):
        expected = self._touch_output("01", None, "LFMIHIFIFF", 3)

        with patch("mrsiprep.interfaces.chimera.run_checked") as run_checked:
            run_checked.return_value = MagicMock(stdout="")
            result = run_chimera(
                self.bids_dir, self.derivatives_dir, self.fs_subjects_dir, self.t1_path, "01", None, "LFMIHIFIFF", 3, 2,
            )

        self.assertEqual(result, expected)

    def test_ids_file_is_written_and_cleaned_up(self):
        self._touch_output("01", "01", "LFMIHIFIFF", 3)
        captured = {}

        def fake_run_checked(cmd, **_kwargs):
            captured["ids_path"] = Path(cmd[cmd.index("-ids") + 1])
            self.assertTrue(captured["ids_path"].exists())
            self.assertEqual(captured["ids_path"].read_text(), f"{self.t1_path.name}\n")
            return MagicMock(stdout="")

        with patch("mrsiprep.interfaces.chimera.run_checked", side_effect=fake_run_checked):
            run_chimera(self.bids_dir, self.derivatives_dir, self.fs_subjects_dir, self.t1_path, "01", "01", "LFMIHIFIFF", 3, 2)

        self.assertFalse(captured["ids_path"].exists())


class MissingOutputTests(RunChimeraFixture):
    def test_raises_with_stdout_when_no_output_found(self):
        with patch("mrsiprep.interfaces.chimera.run_checked") as run_checked:
            run_checked.return_value = MagicMock(stdout="chimera log tail")
            with self.assertRaisesRegex(ChimeraError, "chimera log tail"):
                run_chimera(self.bids_dir, self.derivatives_dir, self.fs_subjects_dir, self.t1_path, "01", "01", "LFMIHIFIFF", 3, 2)


class ForceRerunTests(RunChimeraFixture):
    def test_force_deletes_stale_matching_output_before_running(self):
        stale = self._touch_output("01", "01", "LFMIHIFIFF", 3)
        fresh = self.derivatives_dir / "chimera" / stale.name

        def fake_run_checked(cmd, **_kwargs):
            self.assertIn("--force", cmd)
            self.assertFalse(stale.exists(), "stale output should be removed before chimera runs")
            fresh.parent.mkdir(parents=True, exist_ok=True)
            fresh.touch()
            return MagicMock(stdout="")

        with patch("mrsiprep.interfaces.chimera.run_checked", side_effect=fake_run_checked):
            result = run_chimera(
                self.bids_dir, self.derivatives_dir, self.fs_subjects_dir, self.t1_path, "01", "01", "LFMIHIFIFF", 3, 2, force=True,
            )

        self.assertEqual(result, fresh)

    def test_force_only_deletes_matching_scheme_and_scale(self):
        other_scheme = self._touch_output("01", "01", "SFMIHIFIS", 2)
        expected = self.derivatives_dir / "chimera" / "sub-01_ses-01_atlas-chimeraLFMIHIFIFF_scale-3_dseg.nii.gz"

        def fake_run_checked(cmd, **_kwargs):
            self.assertTrue(other_scheme.exists(), "a different scheme/scale output must not be touched by --force cleanup")
            expected.parent.mkdir(parents=True, exist_ok=True)
            expected.touch()
            return MagicMock(stdout="")

        with patch("mrsiprep.interfaces.chimera.run_checked", side_effect=fake_run_checked):
            run_chimera(self.bids_dir, self.derivatives_dir, self.fs_subjects_dir, self.t1_path, "01", "01", "LFMIHIFIFF", 3, 2, force=True)


class MilestonesTests(RunChimeraFixture):
    def test_milestones_sets_env_var_and_forces_stdout_streaming(self):
        self._touch_output("01", "01", "LFMIHIFIFF", 3)

        with patch("mrsiprep.interfaces.chimera.run_checked") as run_checked:
            run_checked.return_value = MagicMock(stdout="")
            run_chimera(
                self.bids_dir, self.derivatives_dir, self.fs_subjects_dir, self.t1_path, "01", "01", "LFMIHIFIFF", 3, 2,
                verbose=False, milestones=True,
            )

        _, kwargs = run_checked.call_args
        self.assertTrue(kwargs["verbose"])
        self.assertEqual(kwargs["env"]["CHIMERA_MILESTONES"], "1")


class DebugHookTests(RunChimeraFixture):
    def test_debug_hooks_are_called_when_debug_object_provided(self):
        self._touch_output("01", "01", "LFMIHIFIFF", 3)
        debug = MagicMock()

        with patch("mrsiprep.interfaces.chimera.run_checked") as run_checked:
            run_checked.return_value = MagicMock(stdout="")
            run_chimera(
                self.bids_dir, self.derivatives_dir, self.fs_subjects_dir, self.t1_path, "01", "01", "LFMIHIFIFF", 3, 2, debug=debug,
            )

        debug.info.assert_called()
        debug.debug.assert_called()


if __name__ == "__main__":
    unittest.main()

import subprocess
import unittest
from unittest.mock import patch

from mrsiprep.utils.subprocess_utils import run_checked


class FakeError(Exception):
    """Distinct type, so tests can prove error_cls is honored."""


def _completed(returncode=0, stdout=None, stderr=None):
    return subprocess.CompletedProcess(args=["tool"], returncode=returncode, stdout=stdout, stderr=stderr)


class RunCheckedPipingTests(unittest.TestCase):
    def test_non_verbose_captures_both_streams_separately(self):
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed()) as run:
            run_checked(["tool", "--flag"])
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.PIPE)
        self.assertTrue(kwargs["text"])

    def test_verbose_inherits_parent_streams_so_tool_output_stays_live(self):
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed()) as run:
            run_checked(["tool"], verbose=True)
        kwargs = run.call_args.kwargs
        self.assertIsNone(kwargs["stdout"])
        self.assertIsNone(kwargs["stderr"])

    def test_merge_stderr_redirects_stderr_into_stdout(self):
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed()) as run:
            run_checked(["tool"], merge_stderr=True)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.STDOUT)

    def test_verbose_wins_over_merge_stderr(self):
        # verbose short-circuits the whole capture decision; merging is
        # meaningless when nothing is being captured.
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed()) as run:
            run_checked(["tool"], verbose=True, merge_stderr=True)
        self.assertIsNone(run.call_args.kwargs["stderr"])

    def test_command_is_passed_through_as_a_list_never_a_shell_string(self):
        cmd = ["tool", "--a", "1"]
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed()) as run:
            run_checked(cmd)
        self.assertEqual(run.call_args.args[0], cmd)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_env_is_forwarded_when_given_and_none_by_default(self):
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed()) as run:
            run_checked(["tool"])
        self.assertIsNone(run.call_args.kwargs["env"])

        env = {"FSLDIR": "/opt/fsl"}
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed()) as run:
            run_checked(["tool"], env=env)
        self.assertEqual(run.call_args.kwargs["env"], env)


class RunCheckedSuccessTests(unittest.TestCase):
    def test_returns_the_completed_process_untouched_on_success(self):
        completed = _completed(stdout="all good")
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=completed):
            self.assertIs(run_checked(["tool"]), completed)

    def test_zero_exit_never_raises_even_with_output_on_stderr(self):
        completed = _completed(returncode=0, stdout="out", stderr="warning: harmless")
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=completed):
            self.assertIs(run_checked(["tool"]), completed)


class RunCheckedFailureTests(unittest.TestCase):
    def test_nonzero_exit_raises_runtime_error_by_default(self):
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed(returncode=2)):
            with self.assertRaises(RuntimeError):
                run_checked(["tool"])

    def test_check_false_returns_result_instead_of_raising(self):
        completed = _completed(returncode=3, stdout="diagnostic")
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=completed):
            result = run_checked(["tool"], check=False)
        self.assertIs(result, completed)
        self.assertEqual(result.returncode, 3)

    def test_error_cls_is_honored(self):
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed(returncode=1)):
            with self.assertRaises(FakeError):
                run_checked(["tool"], error_cls=FakeError)

    def test_message_defaults_to_the_binary_name_and_carries_the_exit_status(self):
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed(returncode=9)):
            with self.assertRaisesRegex(RuntimeError, r"^mri_synthseg exited with status 9"):
                run_checked(["mri_synthseg", "--i", "x.nii"])

    def test_error_prefix_overrides_the_binary_name(self):
        # fsl.py passes error_prefix="fast" even though cmd[0] may be a full
        # path, so the message names the tool rather than an install path.
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, r"^fast exited with status 1"):
                run_checked(["/opt/fsl/bin/fast"], error_prefix="fast")

    def test_captured_stdout_is_appended_to_the_message(self):
        completed = _completed(returncode=1, stdout="segfault in stage 2")
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "segfault in stage 2"):
                run_checked(["tool"])

    def test_both_streams_are_appended_when_not_merged(self):
        completed = _completed(returncode=1, stdout="out-text", stderr="err-text")
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=completed):
            with self.assertRaises(RuntimeError) as ctx:
                run_checked(["tool"])
        self.assertIn("out-text", str(ctx.exception))
        self.assertIn("err-text", str(ctx.exception))

    def test_stderr_is_not_appended_twice_when_merged_into_stdout(self):
        # With merge_stderr=True the child's stderr already landed in stdout;
        # .stderr is None, and appending it again would duplicate the text.
        completed = _completed(returncode=1, stdout="merged-output", stderr=None)
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=completed):
            with self.assertRaises(RuntimeError) as ctx:
                run_checked(["tool"], merge_stderr=True)
        self.assertEqual(str(ctx.exception).count("merged-output"), 1)

    def test_empty_output_leaves_a_clean_single_line_message(self):
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed(returncode=4, stdout="", stderr="")):
            with self.assertRaises(RuntimeError) as ctx:
                run_checked(["tool"])
        self.assertEqual(str(ctx.exception), "tool exited with status 4")

    def test_verbose_failure_reports_status_without_captured_output(self):
        # Nothing was captured (streams were inherited), so the message is
        # just the status line -- the output already went to the console.
        with patch("mrsiprep.utils.subprocess_utils.subprocess.run", return_value=_completed(returncode=5)):
            with self.assertRaises(RuntimeError) as ctx:
                run_checked(["tool"], verbose=True)
        self.assertEqual(str(ctx.exception), "tool exited with status 5")


if __name__ == "__main__":
    unittest.main()

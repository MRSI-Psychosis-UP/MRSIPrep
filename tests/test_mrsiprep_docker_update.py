"""Tests for mrsiprep-docker's --update flag (wrapper/src/mrsiprep_docker).

The wrapper is a separate, independently-published package (not part of the
mrsiprep package itself), so its source directory is added to sys.path here
rather than being installed as a dependency.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

WRAPPER_SRC = str(Path(__file__).resolve().parent.parent / "wrapper" / "src")
if WRAPPER_SRC not in sys.path:
    sys.path.insert(0, WRAPPER_SRC)

from mrsiprep_docker.__main__ import main  # noqa: E402


class UpdateFlagTests(unittest.TestCase):
    def test_pulls_the_configured_image_and_exits_zero(self):
        with patch("mrsiprep_docker.__main__.check_docker", return_value=1), patch(
            "mrsiprep_docker.__main__.subprocess.run"
        ) as run, patch("sys.argv", ["mrsiprep-docker", "--update"]):
            run.return_value.returncode = 0
            code = main()
        self.assertEqual(code, 0)
        run.assert_called_once_with(["docker", "pull", "mrsiup/mrsiprep:cpu"])

    def test_respects_a_custom_image(self):
        with patch("mrsiprep_docker.__main__.check_docker", return_value=1), patch(
            "mrsiprep_docker.__main__.subprocess.run"
        ) as run, patch("sys.argv", ["mrsiprep-docker", "--update", "--image", "mrsiup/mrsiprep:gpu"]):
            run.return_value.returncode = 0
            code = main()
        self.assertEqual(code, 0)
        run.assert_called_once_with(["docker", "pull", "mrsiup/mrsiprep:gpu"])

    def test_does_not_require_bids_dir_or_output_dir(self):
        """--update alone must not fall into the no-args-shows-help branch."""
        with patch("mrsiprep_docker.__main__.check_docker", return_value=1), patch(
            "mrsiprep_docker.__main__.subprocess.run"
        ) as run, patch("builtins.print") as mock_print, patch("sys.argv", ["mrsiprep-docker", "--update"]):
            run.return_value.returncode = 0
            main()
        printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
        self.assertNotIn("usage:", printed)

    def test_propagates_a_failed_pull(self):
        with patch("mrsiprep_docker.__main__.check_docker", return_value=1), patch(
            "mrsiprep_docker.__main__.subprocess.run"
        ) as run, patch("sys.argv", ["mrsiprep-docker", "--update"]):
            run.return_value.returncode = 1
            code = main()
        self.assertEqual(code, 1)

    def test_fails_cleanly_when_docker_is_not_installed(self):
        with patch("mrsiprep_docker.__main__.check_docker", return_value=-1), patch(
            "mrsiprep_docker.__main__.subprocess.run"
        ) as run, patch("sys.argv", ["mrsiprep-docker", "--update"]):
            code = main()
        self.assertEqual(code, 1)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

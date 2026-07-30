import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.cli.run import main
from mrsiprep.workflows.participant import RecordingStatus


def _config(**overrides):
    base = dict(
        verbose=0,
        logs_dir=None,
        analysis_level="participant",
        check_external_libs=False,
        validate_only=False,
        nproc=1,
        nthreads=1,
    )
    base.update(overrides)
    config = SimpleNamespace(**base)
    config.resolve_cpu_budget = lambda: (config.nproc, config.nthreads, None)
    return config


class MainListPresetsTests(unittest.TestCase):
    def test_list_presets_short_circuits_before_parsing(self):
        with patch("mrsiprep.cli.run.print_presets") as print_presets, patch("mrsiprep.cli.run.parse_args") as parse_args:
            code = main(["--list-presets"])
        self.assertEqual(code, 0)
        print_presets.assert_called_once()
        parse_args.assert_not_called()


class MainAnalysisLevelTests(unittest.TestCase):
    def test_non_participant_analysis_level_returns_2(self):
        config = _config(analysis_level="group")
        with patch("mrsiprep.cli.run.parse_args", return_value=config):
            code = main([])
        self.assertEqual(code, 2)


class MainCheckExternalLibsTests(unittest.TestCase):
    def test_returns_0_when_all_tools_available(self):
        config = _config(check_external_libs=True)
        with patch("mrsiprep.cli.run.parse_args", return_value=config), patch("mrsiprep.cli.run.check_external_software", return_value=True):
            code = main([])
        self.assertEqual(code, 0)

    def test_returns_1_when_tools_missing(self):
        config = _config(check_external_libs=True)
        with patch("mrsiprep.cli.run.parse_args", return_value=config), patch("mrsiprep.cli.run.check_external_software", return_value=False):
            code = main([])
        self.assertEqual(code, 1)


class MainValidateOnlyTests(unittest.TestCase):
    def test_returns_0_when_all_recordings_valid(self):
        config = _config(validate_only=True)
        statuses = [RecordingStatus("S001", "V1", "success")]
        with patch("mrsiprep.cli.run.parse_args", return_value=config), patch("mrsiprep.cli.run.validate_participant_inputs", return_value=statuses):
            code = main([])
        self.assertEqual(code, 0)

    def test_returns_1_when_any_recording_invalid(self):
        config = _config(validate_only=True)
        statuses = [RecordingStatus("S001", "V1", "success"), RecordingStatus("S002", None, "failed", error="boom")]
        with patch("mrsiprep.cli.run.parse_args", return_value=config), patch("mrsiprep.cli.run.validate_participant_inputs", return_value=statuses):
            code = main([])
        self.assertEqual(code, 1)


class MainParticipantRunTests(unittest.TestCase):
    def test_returns_0_when_all_recordings_succeed(self):
        config = _config()
        statuses = [RecordingStatus("S001", "V1", "success")]
        with patch("mrsiprep.cli.run.parse_args", return_value=config), patch("mrsiprep.cli.run.run_participant_workflow", return_value=statuses):
            code = main([])
        self.assertEqual(code, 0)

    def test_returns_1_when_all_recordings_fail(self):
        config = _config()
        statuses = [RecordingStatus("S001", "V1", "failed", error="boom")]
        with patch("mrsiprep.cli.run.parse_args", return_value=config), patch("mrsiprep.cli.run.run_participant_workflow", return_value=statuses):
            code = main([])
        self.assertEqual(code, 1)

    def test_returns_0_when_partially_successful(self):
        config = _config()
        statuses = [RecordingStatus("S001", "V1", "success"), RecordingStatus("S002", None, "failed", error="boom")]
        with patch("mrsiprep.cli.run.parse_args", return_value=config), patch("mrsiprep.cli.run.run_participant_workflow", return_value=statuses):
            code = main([])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

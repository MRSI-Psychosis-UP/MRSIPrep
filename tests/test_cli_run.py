import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mrsiprep.cli.run import main
from mrsiprep.workflows.participant import RecordingStatus


def _config(**overrides):
    base = dict(
        verbose=0,
        logs_dir=None,
        analysis_level="participant",
        check_external_libs=False,
        validate_only=False,
        reports_only=False,
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


class MainReportsOnlyTests(unittest.TestCase):
    def test_returns_0_when_all_recordings_succeed(self):
        config = _config(reports_only=True)
        statuses = [RecordingStatus("S001", "V1", "success")]
        with patch("mrsiprep.cli.run.parse_args", return_value=config), patch("mrsiprep.cli.run.run_reports_only_workflow", return_value=statuses):
            code = main([])
        self.assertEqual(code, 0)

    def test_returns_1_when_all_recordings_fail(self):
        config = _config(reports_only=True)
        statuses = [RecordingStatus("S001", "V1", "failed", error="boom")]
        with patch("mrsiprep.cli.run.parse_args", return_value=config), patch("mrsiprep.cli.run.run_reports_only_workflow", return_value=statuses):
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


class NativeThreadLimitTests(unittest.TestCase):
    """OpenMP and OpenBLAS default to the machine's full core count inside
    *every* worker, so --nproc 4 --nthreads 8 really asks for 4x32 threads on a
    32-core host. Capping them to --nthreads is what makes the CPU budget mean
    what it says."""

    def _config(self, nproc=2, nthreads=8):
        cfg = SimpleNamespace(nproc=nproc, nthreads=nthreads)
        cfg.resolve_cpu_budget = lambda: (nproc, nthreads, None)
        return cfg

    def test_limits_are_set_from_nthreads(self):
        from mrsiprep.cli.run import _THREAD_LIMIT_VARS, _apply_resolved_cpu_budget

        with patch.dict(os.environ, {}, clear=True):
            _apply_resolved_cpu_budget(self._config(nthreads=6), MagicMock())
            for name in _THREAD_LIMIT_VARS:
                self.assertEqual(os.environ[name], "6", msg=name)

    def test_an_explicit_user_setting_is_not_overridden(self):
        """Someone tuning OMP_NUM_THREADS deliberately should keep their value."""
        from mrsiprep.cli.run import _apply_resolved_cpu_budget

        with patch.dict(os.environ, {"OMP_NUM_THREADS": "2"}, clear=True):
            _apply_resolved_cpu_budget(self._config(nthreads=8), MagicMock())
            self.assertEqual(os.environ["OMP_NUM_THREADS"], "2")
            self.assertEqual(os.environ["OPENBLAS_NUM_THREADS"], "8")

    def test_the_coerced_budget_is_what_gets_applied(self):
        from mrsiprep.cli.run import _apply_resolved_cpu_budget

        cfg = SimpleNamespace(nproc=4, nthreads=32)
        cfg.resolve_cpu_budget = lambda: (4, 8, "coerced")
        logger = MagicMock()
        with patch.dict(os.environ, {}, clear=True):
            _apply_resolved_cpu_budget(cfg, logger)
            # Inside the patch: outside it os.environ is already restored.
            self.assertEqual(os.environ["OMP_NUM_THREADS"], "8")
        self.assertEqual(cfg.nthreads, 8)
        logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()

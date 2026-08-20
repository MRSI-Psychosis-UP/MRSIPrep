import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mrsiprep.io.bids import Recording
from mrsiprep.workflows.nipype_engine.run import (
    _configure_nipype_logging,
    _run_one_recording_nipype,
    _terminal_outputs,
    execute_recordings_nipype,
)
from mrsiprep.workflows.participant import RecordingStatus


class ConfigureNipypeLoggingTests(unittest.TestCase):
    def test_low_verbosity_uses_critical_level(self):
        config = SimpleNamespace(verbose=1)
        with patch("nipype.config") as ncfg, patch("nipype.logging") as nlogging:
            _configure_nipype_logging(config)
        level_cfg = ncfg.update_config.call_args[0][0]
        self.assertEqual(level_cfg["logging"]["workflow_level"], "CRITICAL")
        nlogging.update_logging.assert_called_once()

    def test_high_verbosity_uses_info_level(self):
        config = SimpleNamespace(verbose=3)
        with patch("nipype.config") as ncfg, patch("nipype.logging"):
            _configure_nipype_logging(config)
        level_cfg = ncfg.update_config.call_args[0][0]
        self.assertEqual(level_cfg["logging"]["interface_level"], "INFO")

    def test_sets_etelemetry_opt_out_env_vars(self):
        import os

        for key in ("NIPYPE_NO_ET", "NO_ET"):
            os.environ.pop(key, None)
        config = SimpleNamespace(verbose=1)
        with patch("nipype.config"), patch("nipype.logging"):
            _configure_nipype_logging(config)
        self.assertEqual(os.environ.get("NIPYPE_NO_ET"), "1")
        self.assertEqual(os.environ.get("NO_ET"), "1")


class ExecuteRecordingsSerialPathTests(unittest.TestCase):
    def test_dispatches_one_call_per_recording_with_matching_template(self):
        ready = [Recording("01", "01"), Recording("02", None)]
        config = SimpleNamespace(nproc=1)
        templates = {"01": "template_for_01"}
        results = [RecordingStatus("01", "01", "success"), RecordingStatus("02", None, "success")]

        with patch("mrsiprep.workflows.nipype_engine.run._configure_nipype_logging"), patch(
            "mrsiprep.workflows.nipype_engine.run._run_one_recording_nipype", side_effect=results
        ) as run_one:
            statuses = execute_recordings_nipype(config, ready, subject_templates=templates)

        self.assertEqual(statuses, results)
        first_call, second_call = run_one.call_args_list
        self.assertEqual(first_call[0], (config, "01", "01", "template_for_01"))
        self.assertEqual(second_call[0], (config, "02", None, None))

    def test_empty_ready_list_returns_empty_without_dispatch(self):
        config = SimpleNamespace(nproc=1)
        with patch("mrsiprep.workflows.nipype_engine.run._configure_nipype_logging"), patch(
            "mrsiprep.workflows.nipype_engine.run._run_one_recording_nipype"
        ) as run_one:
            statuses = execute_recordings_nipype(config, [])
        run_one.assert_not_called()
        self.assertEqual(statuses, [])

    def test_none_subject_templates_defaults_to_empty_dict(self):
        ready = [Recording("01", "01")]
        config = SimpleNamespace(nproc=1)
        with patch("mrsiprep.workflows.nipype_engine.run._configure_nipype_logging"), patch(
            "mrsiprep.workflows.nipype_engine.run._run_one_recording_nipype", return_value=RecordingStatus("01", "01", "success")
        ) as run_one:
            execute_recordings_nipype(config, ready, subject_templates=None)
        self.assertIsNone(run_one.call_args[0][3])


class ExecuteRecordingsParallelPathTests(unittest.TestCase):
    def test_dispatches_via_process_pool_and_collects_all_results(self):
        ready = [Recording("01", "01"), Recording("02", None)]
        config = SimpleNamespace(nproc=2)

        future_01 = MagicMock()
        future_01.result.return_value = RecordingStatus("01", "01", "success")
        future_02 = MagicMock()
        future_02.result.return_value = RecordingStatus("02", None, "failed", error="boom")

        executor_instance = MagicMock()
        executor_instance.__enter__.return_value = executor_instance
        executor_instance.__exit__.return_value = False
        executor_instance.submit.side_effect = [future_01, future_02]

        stop_event = MagicMock()
        listener_thread = MagicMock()

        with patch("mrsiprep.workflows.nipype_engine.run._configure_nipype_logging"), patch(
            "multiprocessing.Manager"
        ) as manager_cls, patch("concurrent.futures.ProcessPoolExecutor", return_value=executor_instance), patch(
            "concurrent.futures.as_completed", side_effect=lambda futures: list(futures.keys())
        ), patch(
            "mrsiprep.workflows.nipype_engine.run._start_live_status_table", return_value=(stop_event, listener_thread)
        ):
            statuses = execute_recordings_nipype(config, ready)

        self.assertEqual(executor_instance.submit.call_count, 2)
        self.assertEqual({s.subject for s in statuses}, {"01", "02"})
        stop_event.set.assert_called_once()
        listener_thread.join.assert_called_once()
        manager_cls.return_value.shutdown.assert_called_once()

    def test_manager_is_shut_down_even_if_a_future_raises(self):
        ready = [Recording("01", "01")]
        config = SimpleNamespace(nproc=2)

        failing_future = MagicMock()
        failing_future.result.side_effect = RuntimeError("subprocess crashed")

        executor_instance = MagicMock()
        executor_instance.__enter__.return_value = executor_instance
        executor_instance.__exit__.return_value = False
        executor_instance.submit.side_effect = [failing_future]

        with patch("mrsiprep.workflows.nipype_engine.run._configure_nipype_logging"), patch(
            "multiprocessing.Manager"
        ) as manager_cls, patch("concurrent.futures.ProcessPoolExecutor", return_value=executor_instance), patch(
            "concurrent.futures.as_completed", side_effect=lambda futures: list(futures.keys())
        ), patch(
            "mrsiprep.workflows.nipype_engine.run._start_live_status_table", return_value=(MagicMock(), MagicMock())
        ):
            with self.assertRaises(RuntimeError):
                execute_recordings_nipype(config, ready)

        manager_cls.return_value.shutdown.assert_called_once()


class TerminalOutputsTests(unittest.TestCase):
    def _node(self, name, ctx):
        node = MagicMock()
        node.name = name
        node.result.outputs.ctx = ctx
        return node

    def test_returns_outputs_from_matching_terminal_node(self):
        exec_graph = MagicMock()
        exec_graph.nodes.return_value = [self._node("reports", {"outputs": {"t1w": "path"}})]
        self.assertEqual(_terminal_outputs(exec_graph, "reports"), {"t1w": "path"})

    def test_returns_empty_dict_when_terminal_node_absent(self):
        exec_graph = MagicMock()
        exec_graph.nodes.return_value = [self._node("prepare", {"outputs": {"t1w": "path"}})]
        self.assertEqual(_terminal_outputs(exec_graph, "reports"), {})

    def test_returns_empty_dict_when_ctx_is_not_a_dict(self):
        exec_graph = MagicMock()
        exec_graph.nodes.return_value = [self._node("reports", "not-a-dict")]
        self.assertEqual(_terminal_outputs(exec_graph, "reports"), {})

    def test_missing_outputs_key_defaults_to_empty_dict(self):
        exec_graph = MagicMock()
        exec_graph.nodes.return_value = [self._node("reports", {})]
        self.assertEqual(_terminal_outputs(exec_graph, "reports"), {})


class RunOneRecordingNipypeFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.config = SimpleNamespace(verbose=0, derivative_dir=self.tmp / "derivatives", stop_on_first_crash=False)
        self._patches = [
            patch("mrsiprep.workflows.nipype_engine.run._configure_nipype_logging"),
            patch("mrsiprep.utils.runtime_metrics.write_runtime_metrics"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmpdir.cleanup()


class RunOneRecordingSuccessTests(RunOneRecordingNipypeFixture):
    def test_success_returns_status_with_terminal_outputs(self):
        fake_wf = MagicMock()
        fake_wf.run.return_value = "exec_graph"
        with patch("mrsiprep.workflows.nipype_engine.build.build_recording_workflow", return_value=fake_wf) as build, patch(
            "mrsiprep.workflows.nipype_engine.run._terminal_outputs", return_value={"t1w": "path"}
        ):
            status = _run_one_recording_nipype(self.config, "01", "01")

        build.assert_called_once_with(self.config, "01", "01", subject_template=None)
        fake_wf.run.assert_called_once_with(plugin="Linear")
        self.assertEqual(status.status, "success")
        self.assertEqual(status.outputs, {"t1w": "path"})


class RunOneRecordingFailureTests(RunOneRecordingNipypeFixture):
    def test_failure_is_caught_and_returns_failed_status(self):
        with patch("mrsiprep.workflows.nipype_engine.build.build_recording_workflow", side_effect=RuntimeError("step exploded")):
            status = _run_one_recording_nipype(self.config, "01", "01")

        self.assertEqual(status.status, "failed")
        self.assertIn("step exploded", status.error)

    def test_stop_on_first_crash_reraises(self):
        self.config.stop_on_first_crash = True
        with patch("mrsiprep.workflows.nipype_engine.build.build_recording_workflow", side_effect=RuntimeError("step exploded")):
            with self.assertRaisesRegex(RuntimeError, "step exploded"):
                _run_one_recording_nipype(self.config, "01", "01")

    def test_logbook_and_status_queue_are_cleared_even_on_failure(self):
        with patch("mrsiprep.workflows.nipype_engine.build.build_recording_workflow", side_effect=RuntimeError("boom")), patch(
            "mrsiprep.utils.debug.set_logbook"
        ) as set_logbook, patch("mrsiprep.utils.debug.set_status_queue") as set_status_queue, patch(
            "mrsiprep.utils.debug.set_timing_sink"
        ) as set_timing_sink:
            _run_one_recording_nipype(self.config, "01", "01")

        set_logbook.assert_called_with(None)
        set_status_queue.assert_called_with(None)
        set_timing_sink.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()

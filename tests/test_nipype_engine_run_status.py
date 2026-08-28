"""Live status table for parallel recordings.

The bug these pin: a recording that had finished still displayed RUNNING.
Two independent causes, either of which reproduces it on its own.
"""

import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.workflows.nipype_engine.run import _start_live_status_table


class _Console:
    """Stands in for rich.Console; the table content is asserted via rows."""

    def __init__(self, *args, **kwargs):
        pass


class LiveStatusTableTests(unittest.TestCase):
    def _run_listener(self, tags, messages, drain_delay=0.0):
        """Feed ``messages``, stop the listener, return the rendered states."""
        config = SimpleNamespace(verbose=1)
        status_queue = queue.Queue()
        captured = {}

        class _Live:
            def __init__(self, renderable, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def update(self, table):
                captured["table"] = table

        with patch("sys.stdout.isatty", return_value=True), patch("rich.console.Console", _Console), patch(
            "rich.live.Live", _Live
        ), patch("rich.table.Table") as table_cls:
            recorded = []
            table_cls.return_value.add_row.side_effect = lambda *row: recorded.append(row)
            stop, thread = _start_live_status_table(config, tags, status_queue)
            for message in messages:
                status_queue.put(message)
            time.sleep(drain_delay)
            stop.set()
            thread.join(timeout=5)
        # add_row is called per tag per render; the last len(tags) calls are the
        # final render.
        return recorded[-len(tags):] if recorded else []

    def test_finished_message_marks_the_row_done(self):
        rows = self._run_listener(
            ["sub-01 ses-01"],
            [("sub-01 ses-01", "always", "START"), ("sub-01 ses-01", "always", "FINISHED")],
        )
        self.assertTrue(rows, "expected a rendered row")
        self.assertIn("DONE", rows[0][1])

    def test_late_step_message_does_not_resurrect_a_finished_row(self):
        rows = self._run_listener(
            ["sub-01 ses-01"],
            [
                ("sub-01 ses-01", "always", "START"),
                ("sub-01 ses-01", "always", "FINISHED"),
                ("sub-01 ses-01", "step", "Reports"),
            ],
        )
        self.assertIn("DONE", rows[0][1])

    def test_failed_recording_renders_failed_not_running(self):
        rows = self._run_listener(
            ["sub-01 ses-01"],
            [("sub-01 ses-01", "always", "START"), ("sub-01 ses-01", "always", "FAILED")],
        )
        self.assertIn("FAILED", rows[0][1])


class TerminalStatusFromParentTests(unittest.TestCase):
    """The parent asserts each recording's outcome itself.

    The worker's FINISHED travels through a manager queue, so it can still be
    in flight when the future resolves -- and a worker that died never sent one
    at all. Either way the row used to stay on RUNNING. This is the
    deterministic half of the fix; the listener's end-of-run drain covers the
    same race from the other side but is timing-dependent by nature.
    """

    def _execute(self, statuses):
        from mrsiprep.workflows.nipype_engine import run as R

        recordings = [SimpleNamespace(subject="01", session="01"), SimpleNamespace(subject="02", session="01")]
        config = SimpleNamespace(nproc=2, verbose=0)
        sent = []

        class _Queue:
            def put(self, item):
                sent.append(item)

        class _Manager:
            def Queue(self):
                return _Queue()

            def shutdown(self):
                pass

        class _Future:
            def __init__(self, value):
                self._value = value

            def result(self):
                return self._value

        futures = {_Future(status): rec for status, rec in zip(statuses, recordings)}

        class _Executor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def submit(self, *args, **kwargs):
                return list(futures)[len(getattr(self, "_seen", []))]

        # A thread that has actually run, so the production code's join() is
        # valid; an unstarted Thread raises RuntimeError on join.
        listener = threading.Thread(target=lambda: None)
        listener.start()

        with patch("multiprocessing.Manager", _Manager), patch.object(
            R, "_start_live_status_table", return_value=(threading.Event(), listener)
        ), patch("concurrent.futures.ProcessPoolExecutor") as pool, patch(
            "concurrent.futures.as_completed", return_value=list(futures)
        ):
            executor = pool.return_value.__enter__.return_value
            executor.submit.side_effect = list(futures)
            R.execute_recordings_nipype(config, recordings)
        return sent

    def test_success_emits_finished_for_its_own_tag(self):
        sent = self._execute([
            SimpleNamespace(status="success"),
            SimpleNamespace(status="success"),
        ])
        self.assertEqual({item[2] for item in sent}, {"FINISHED"})
        self.assertEqual({item[0] for item in sent}, {"sub-01 ses-01", "sub-02 ses-01"})

    def test_failure_emits_failed_not_finished(self):
        sent = self._execute([
            SimpleNamespace(status="failed"),
            SimpleNamespace(status="success"),
        ])
        self.assertIn("FAILED", {item[2] for item in sent})


if __name__ == "__main__":
    unittest.main()

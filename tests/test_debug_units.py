"""Tests for utils/debug.py beyond step()'s timing behavior (already
covered by test_debug_timing.py): logbook writing, verbosity gating,
message preparation/tagging, and the status-queue short-circuit path.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mrsiprep.utils.debug import Debug, _logbook_write, _strip_markup, collect_timings, set_logbook, set_status_queue, set_timing_sink, timestamp


class _ResetGlobalDebugStateMixin:
    """_LOGBOOK/_STATUS_QUEUE/_TIMINGS are process-global module state; reset
    them before AND after every test so no test's correctness depends on
    what ran before it (a test class here arming the status queue, for
    instance, must never leak into an unrelated test elsewhere in the file)."""

    def setUp(self):
        set_logbook(None)
        set_status_queue(None)
        set_timing_sink(False)
        super().setUp()

    def tearDown(self):
        set_logbook(None)
        set_status_queue(None)
        set_timing_sink(False)
        super().tearDown()


class TimestampTests(_ResetGlobalDebugStateMixin, unittest.TestCase):
    def test_matches_day_month_hour_minute_format(self):
        self.assertRegex(timestamp(), r"^\d{2}/\d{2}-\d{2}:\d{2}$")


class StripMarkupTests(_ResetGlobalDebugStateMixin, unittest.TestCase):
    def test_removes_rich_markup_tags(self):
        self.assertEqual(_strip_markup("[success]done[/success]"), "done")

    def test_plain_text_unchanged(self):
        self.assertEqual(_strip_markup("plain text"), "plain text")


class LogbookTests(_ResetGlobalDebugStateMixin, unittest.TestCase):
    def test_set_logbook_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "log.txt"
            set_logbook(path)
            self.assertTrue(path.parent.is_dir())

    def test_set_logbook_none_disables_writes(self):
        set_logbook(None)
        _logbook_write("INFO", "should not raise or write anywhere")  # must not raise

    def test_write_appends_timestamped_stripped_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "log.txt"
            set_logbook(path)
            _logbook_write("SUCCESS", "[success]all good[/success]")
            content = path.read_text()
        self.assertIn("SUCCESS", content)
        self.assertIn("all good", content)
        self.assertNotIn("[success]", content)

    def test_empty_message_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "log.txt"
            set_logbook(path)
            _logbook_write("INFO", "")
            path.touch()  # ensure file exists so read_text doesn't raise
            self.assertEqual(path.read_text(), "")

    def test_multiple_writes_append_rather_than_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "log.txt"
            set_logbook(path)
            _logbook_write("INFO", "first")
            _logbook_write("INFO", "second")
            content = path.read_text()
        self.assertIn("first", content)
        self.assertIn("second", content)


class PrepareMessageTests(_ResetGlobalDebugStateMixin, unittest.TestCase):
    def test_no_messages_returns_empty_strings(self):
        debug = Debug(verbose=1)
        self.assertEqual(debug._prepare_message(), ("", ""))

    def test_joins_multiple_messages_with_space(self):
        debug = Debug(verbose=1)
        _prefix, text = debug._prepare_message("hello", "world")
        self.assertEqual(text, "hello world")

    def test_leading_blank_first_arg_becomes_prefix(self):
        debug = Debug(verbose=1)
        prefix, text = debug._prepare_message("\n", "message")
        self.assertEqual(prefix, "\n")
        self.assertEqual(text, "message")

    def test_tag_is_prepended_to_nonempty_text(self):
        debug = Debug(verbose=1, tag="sub-01")
        _prefix, text = debug._prepare_message("hello")
        self.assertEqual(text, "[sub-01] hello")

    def test_tag_alone_when_no_text(self):
        debug = Debug(verbose=1, tag="sub-01")
        _prefix, text = debug._prepare_message("\n")
        self.assertEqual(text, "[sub-01]")


class EmitStatusTests(_ResetGlobalDebugStateMixin, unittest.TestCase):
    def test_returns_false_when_no_queue_armed(self):
        debug = Debug(verbose=1, tag="sub-01")
        self.assertFalse(debug._emit_status("info", "message"))

    def test_puts_tagged_message_on_queue_when_armed(self):
        queue = MagicMock()
        set_status_queue(queue)
        debug = Debug(verbose=1, tag="sub-01")
        result = debug._emit_status("info", "message")
        self.assertTrue(result)
        queue.put.assert_called_once_with(("sub-01", "info", "message"))

    def test_queue_exception_is_swallowed_and_returns_false(self):
        queue = MagicMock()
        queue.put.side_effect = RuntimeError("queue closed")
        set_status_queue(queue)
        debug = Debug(verbose=1)
        self.assertFalse(debug._emit_status("info", "message"))


class VerbosityGatingTests(_ResetGlobalDebugStateMixin, unittest.TestCase):
    def _debug(self, verbose):
        debug = Debug(verbose=verbose)
        debug.console = MagicMock()
        return debug

    def test_always_prints_regardless_of_verbosity(self):
        debug = self._debug(0)
        debug.always("message")
        debug.console.print.assert_called_once()

    def test_success_suppressed_below_verbose_2(self):
        debug = self._debug(1)
        debug.success("message")
        debug.console.print.assert_not_called()

    def test_success_printed_at_verbose_2(self):
        debug = self._debug(2)
        debug.success("message")
        debug.console.print.assert_called_once()

    def test_error_suppressed_below_verbose_2(self):
        debug = self._debug(1)
        debug.error("message")
        debug.console.print.assert_not_called()

    def test_warning_suppressed_below_verbose_2(self):
        debug = self._debug(1)
        debug.warning("message")
        debug.console.print.assert_not_called()

    def test_failure_suppressed_below_verbose_2(self):
        debug = self._debug(1)
        debug.failure("message")
        debug.console.print.assert_not_called()

    def test_info_requires_verbose_2(self):
        debug = self._debug(1)
        debug.info("message")
        debug.console.print.assert_not_called()
        debug2 = self._debug(2)
        debug2.info("message")
        debug2.console.print.assert_called_once()

    def test_debug_requires_verbose_3(self):
        debug = self._debug(2)
        debug.debug("message")
        debug.console.print.assert_not_called()
        debug3 = self._debug(3)
        debug3.debug("message")
        debug3.console.print.assert_called_once()

    def test_logbook_still_written_even_when_console_output_suppressed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "log.txt"
            set_logbook(path)
            debug = self._debug(0)
            debug.error("quiet but logged")
            content = path.read_text()
        self.assertIn("quiet but logged", content)

    def test_status_queue_short_circuits_console_print(self):
        queue = MagicMock()
        set_status_queue(queue)
        debug = self._debug(2)
        debug.success("message")
        debug.console.print.assert_not_called()
        queue.put.assert_called_once()


class ExceptionMethodTests(_ResetGlobalDebugStateMixin, unittest.TestCase):
    def test_tag_prepended_to_logged_summary(self):
        # Tests exception()'s own contract (it prepends the tag before
        # handing off to _logbook_write) in isolation from
        # _logbook_write/_strip_markup's downstream behavior: Rich's
        # markup parser treats a bare "[sub-01]" prefix as a style tag and
        # silently drops it from the *file* content, so asserting on the
        # written file's text here would test _strip_markup, not exception().
        with patch("mrsiprep.utils.debug._logbook_write") as logbook_write:
            debug = Debug(verbose=0, tag="sub-01")
            debug.exception("boom", "traceback here")
        summary_call = next(c for c in logbook_write.call_args_list if c.args[0] == "ERROR")
        self.assertEqual(summary_call.args[1], "[sub-01] boom")
        trace_call = next(c for c in logbook_write.call_args_list if c.args[0] == "TRACE")
        self.assertEqual(trace_call.args[1], "traceback here")

    def test_logged_tag_prefix_does_not_survive_markup_stripping(self):
        """Documents a real quirk, not a requirement: Rich's Text.from_markup
        treats any "[word]" as a style-open tag, so a tag prefix added by
        plain string concatenation (not markup-escaped) vanishes from the
        logbook *file* even though it renders correctly on the console
        (which uses rich.markup.escape() instead). Low real-world impact
        since one logbook file is already scoped to a single recording, but
        worth knowing if anything ever greps logbooks for the tag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "log.txt"
            set_logbook(path)
            debug = Debug(verbose=0, tag="sub-01")
            debug.exception("boom", "traceback here")
            content = path.read_text()
        self.assertNotIn("[sub-01]", content)
        self.assertIn("boom", content)

    def test_traceback_only_printed_at_verbose_3(self):
        debug = Debug(verbose=2)
        debug.console = MagicMock()
        debug.exception("boom", "full traceback")
        debug.console.print.assert_not_called()

        debug3 = Debug(verbose=3)
        debug3.console = MagicMock()
        debug3.exception("boom", "full traceback")
        debug3.console.print.assert_called_once()


class SeparatorAndTitleTests(_ResetGlobalDebugStateMixin, unittest.TestCase):
    def test_separator_suppressed_at_verbose_0(self):
        debug = Debug(verbose=0)
        debug.console = MagicMock()
        debug.separator()
        debug.console.rule.assert_not_called()

    def test_separator_shown_at_verbose_1(self):
        debug = Debug(verbose=1)
        debug.console = MagicMock()
        debug.separator()
        debug.console.rule.assert_called_once()

    def test_title_suppressed_at_verbose_0(self):
        debug = Debug(verbose=0)
        debug.console = MagicMock()
        debug.title("My Title")
        debug.console.rule.assert_not_called()

    def test_title_shown_at_verbose_1(self):
        debug = Debug(verbose=1)
        debug.console = MagicMock()
        debug.title("My Title")
        debug.console.rule.assert_called_once_with("My Title", style="debug")


class StepMethodTests(_ResetGlobalDebugStateMixin, unittest.TestCase):
    def test_verbose_0_yields_without_printing(self):
        debug = Debug(verbose=0)
        debug.console = MagicMock()
        with debug.step("Quiet step"):
            pass
        debug.console.print.assert_not_called()

    def test_status_queue_mode_emits_step_then_step_done(self):
        queue = MagicMock()
        set_status_queue(queue)
        debug = Debug(verbose=1, tag="sub-01")
        debug.console = MagicMock()
        with debug.step("Working"):
            pass
        kinds = [call.args[0][1] for call in queue.put.call_args_list]
        self.assertEqual(kinds, ["step", "step_done"])
        debug.console.print.assert_not_called()

    def test_status_queue_mode_emits_step_failed_on_exception(self):
        queue = MagicMock()
        set_status_queue(queue)
        debug = Debug(verbose=1)
        debug.console = MagicMock()
        with self.assertRaises(ValueError):
            with debug.step("Failing"):
                raise ValueError("boom")
        kinds = [call.args[0][1] for call in queue.put.call_args_list]
        self.assertEqual(kinds, ["step", "step_failed"])

    def test_non_live_terminal_prints_plain_start_and_success_lines(self):
        debug = Debug(verbose=1)
        debug.console = MagicMock()
        debug._is_live_terminal = False
        with debug.step("Plain step"):
            pass
        # blank-line spacer + PROC start line + SUCCESS end line.
        self.assertEqual(debug.console.print.call_count, 3)

    def test_non_live_terminal_prints_failure_line_and_reraises(self):
        debug = Debug(verbose=1)
        debug.console = MagicMock()
        debug._is_live_terminal = False
        with self.assertRaises(ValueError):
            with debug.step("Plain failing step"):
                raise ValueError("boom")
        last_call_text = str(debug.console.print.call_args_list[-1])
        self.assertIn("failure", last_call_text)

    def test_live_false_forces_plain_output_even_on_live_terminal(self):
        debug = Debug(verbose=1)
        debug.console = MagicMock()
        debug._is_live_terminal = True
        with debug.step("Non-animated step", live=False):
            pass
        debug.console.status.assert_not_called()
        # blank-line spacer + PROC start line + SUCCESS end line.
        self.assertEqual(debug.console.print.call_count, 3)

    def test_live_terminal_uses_console_status_spinner(self):
        debug = Debug(verbose=1)
        debug.console = MagicMock()
        debug._is_live_terminal = True
        with debug.step("Animated step"):
            pass
        debug.console.status.assert_called_once()

    def test_timing_recorded_regardless_of_status_queue_or_verbosity(self):
        set_timing_sink(True)
        queue = MagicMock()
        set_status_queue(queue)
        debug = Debug(verbose=0)
        with debug.step("Silent but timed"):
            pass
        timings = collect_timings()
        self.assertEqual(len(timings), 1)
        self.assertEqual(timings[0]["step"], "Silent but timed")


if __name__ == "__main__":
    unittest.main()

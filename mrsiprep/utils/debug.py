from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.markup import escape
from rich.theme import Theme

# Per-process logbook sink. When set (via set_logbook), every Debug message is
# also appended, timestamped and stripped of Rich markup, to this file. Set
# per subject/session by the workflow runner so each recording gets its own
# logbook inside its output folder. Process-local, so it works under the
# ProcessPoolExecutor fan-out (each --nproc worker keeps its own sink).
_LOGBOOK: Path | None = None


def timestamp() -> str:
    """Day/month-hour:minute, e.g. 06/07-10:54."""
    return datetime.now().strftime("%d/%m-%H:%M")


def set_logbook(path: str | Path | None) -> None:
    global _LOGBOOK
    _LOGBOOK = Path(path) if path is not None else None
    if _LOGBOOK is not None:
        _LOGBOOK.parent.mkdir(parents=True, exist_ok=True)


def _strip_markup(message: str) -> str:
    try:
        from rich.text import Text

        return Text.from_markup(message).plain
    except Exception:
        return message


def _logbook_write(level: str, message: str) -> None:
    if _LOGBOOK is None or not message:
        return
    try:
        with open(_LOGBOOK, "a", encoding="utf-8") as handle:
            handle.write(f"{timestamp()} {level:<7} {_strip_markup(message)}\n")
    except OSError:
        pass


class Debug:
    """Leveled console output.

    Verbosity levels:
      0 - only subject start/finish + elapsed time.
      1 - also show which processing step is currently running.
      2 - also show step-level details (info/success/warning/error messages).
      3 - also let external tools (ANTs, recon-all, mri_synthseg) print their own
          raw output instead of being captured/suppressed.
    """

    def __init__(self, verbose: int | bool = 1):
        custom_theme = Theme(
            {
                "success": "green",
                "error": "red",
                "warning": "yellow",
                "failure": "bold red",
                "info": "blue",
                "proc": "violet",
                "debug": "magenta",
            }
        )
        # Docker's stdout is often not a TTY, which makes rich auto-disable
        # color; force it on unless the user opted out via NO_COLOR.
        force_color = not os.environ.get("NO_COLOR")
        # When stdout isn't a real TTY (e.g. piped into Docker logs), rich
        # falls back to an 80-column default, which truncates wide tables
        # (preflight input availability) regardless of the actual terminal
        # size. Force a wider fixed width in that case.
        import sys

        self._is_live_terminal = sys.stdout.isatty()
        console_width = None if self._is_live_terminal else 200
        self.console = Console(theme=custom_theme, force_terminal=force_color, color_system="standard" if force_color else None, width=console_width)
        self.verbose = int(verbose)

    def _prepare_message(self, *messages):
        if not messages:
            return "", ""
        prefix = ""
        items = list(messages)
        first = str(items[0])
        if first.strip() == "":
            prefix = first
            items = items[1:]
        text = " ".join(str(message) for message in items) if items else ""
        return prefix, text

    @property
    def show_tool_output(self) -> bool:
        """Whether external tools (ANTs/recon-all/mri_synthseg) should print their raw output."""
        return self.verbose >= 3

    def always(self, *messages):
        """Prints regardless of verbosity level (e.g. subject start/finish, elapsed time)."""
        prefix, message = self._prepare_message(*messages)
        self.console.print(f"{prefix}{timestamp()} {escape(message)}")
        _logbook_write("", message)

    def success(self, *messages):
        prefix, message = self._prepare_message(*messages)
        _logbook_write("SUCCESS", message)
        if self.verbose >= 2:
            self.console.print(f"{prefix}{timestamp()} [success][ SUCCESS ][/success] {escape(message)}")

    def error(self, *messages):
        prefix, message = self._prepare_message(*messages)
        _logbook_write("ERROR", message)
        if self.verbose >= 2:
            self.console.print(f"{prefix}{timestamp()} [error][  ERROR  ][/error] {escape(message)}")

    def warning(self, *messages):
        prefix, message = self._prepare_message(*messages)
        _logbook_write("WARNING", message)
        if self.verbose >= 2:
            self.console.print(f"{prefix}{timestamp()} [warning][ WARNING ][/warning] {escape(message)}")

    def failure(self, *messages):
        prefix, message = self._prepare_message(*messages)
        _logbook_write("FAILURE", message)
        if self.verbose >= 2:
            self.console.print(f"{prefix}{timestamp()} [failure][ FAILURE ][/failure] {escape(message)}")

    def info(self, *messages):
        prefix, message = self._prepare_message(*messages)
        _logbook_write("INFO", message)
        if self.verbose >= 2:
            self.console.print(f"{prefix}{timestamp()} [info][   INFO  ][/info] {escape(message)}")

    def proc(self, *messages):
        prefix, message = self._prepare_message(*messages)
        _logbook_write("PROC", message)
        if self.verbose >= 1:
            self.console.print()
            self.console.print(f"{prefix}{timestamp()} [proc][  PROC  ][/proc] {escape(message)}")

    def debug(self, *messages):
        """Fine-grained detail below info(), only shown at verbose >= 3."""
        prefix, message = self._prepare_message(*messages)
        _logbook_write("DEBUG", message)
        if self.verbose >= 3:
            self.console.print(f"{prefix}{timestamp()} [debug][  DEBUG  ][/debug] {escape(message)}")

    @contextmanager
    def step(self, *messages, live: bool = True):
        """Like `proc()`, but shows a live spinner while the `with` body runs and
        replaces it with a checkmark on success (or a cross on exception).

        Falls back to plain start/end lines (no animation) when stdout is not an
        interactive terminal, so piped/redirected output (e.g. Docker logs) stays
        clean instead of filling with overwritten-line artifacts. Pass
        `live=False` when the step's body renders its own rich `Live` display
        (e.g. a `rich.progress.Progress` bar) — nesting two `Live` regions on the
        terminal makes both unreadable, so the step falls back to the same plain
        start/end lines used for non-interactive terminals.
        """
        if self.verbose < 1:
            yield
            return

        prefix, message = self._prepare_message(*messages)
        escaped = escape(message)
        _logbook_write("PROC", message)
        self.console.print()

        if not self._is_live_terminal or not live:
            self.console.print(f"{prefix}{timestamp()} [proc][  PROC  ][/proc] {escaped}")
            try:
                yield
            except BaseException:
                _logbook_write("FAIL", message)
                self.console.print(f"{prefix}{timestamp()} [failure][   ✗    ][/failure] {escaped}")
                raise
            else:
                _logbook_write("DONE", message)
                self.console.print(f"{prefix}{timestamp()} [success][   ✓    ][/success] {escaped}")
            return

        with self.console.status(f"{prefix}{timestamp()} [proc][  PROC  ][/proc] {escaped}", spinner="dots") as status:
            try:
                yield
            except BaseException:
                status.stop()
                _logbook_write("FAIL", message)
                self.console.print(f"{prefix}{timestamp()} [failure][   ✗    ][/failure] {escaped}")
                raise
            else:
                status.stop()
                _logbook_write("DONE", message)
                self.console.print(f"{prefix}{timestamp()} [success][   ✓    ][/success] {escaped}")

    def separator(self):
        if self.verbose >= 1:
            self.console.rule()

    def title(self, title: str):
        if self.verbose >= 1:
            self.console.rule(title, style="debug")

    def __progress_bar_task(self, duration: int):
        from rich.progress import Progress

        with Progress() as progress:
            task = progress.add_task("[green]Registration...", total=duration)
            for _ in range(duration):
                time.sleep(1)
                progress.update(task, advance=1)

    def run_progress_bar_in_background(self, duration: int):
        thread = threading.Thread(target=self.__progress_bar_task, args=(duration,), daemon=True)
        thread.start()

"""Shared subprocess execution helper for external-tool wrappers."""

from __future__ import annotations

import subprocess


def run_checked(
    cmd: list[str],
    *,
    verbose: bool = False,
    check: bool = True,
    merge_stderr: bool = False,
    env: dict | None = None,
    error_cls: type[Exception] = RuntimeError,
    error_prefix: str | None = None,
) -> subprocess.CompletedProcess:
    """Run `cmd`, gating stdout/stderr capture on `verbose`.

    When `verbose` is True, the subprocess inherits the parent's stdout/stderr
    so the tool's own output streams live. Otherwise output is captured as
    text. When `check` is True (the default) a nonzero exit raises
    `error_cls` with the captured output appended; pass `check=False` when
    the caller needs to inspect `.returncode`/`.stdout` itself (e.g. to
    build a more specific error message) instead of having one raised here.
    """
    result = subprocess.run(
        cmd,
        stdout=None if verbose else subprocess.PIPE,
        stderr=None if verbose else (subprocess.STDOUT if merge_stderr else subprocess.PIPE),
        text=True,
        env=env,
    )
    if check and result.returncode != 0:
        prefix = error_prefix or cmd[0]
        output = f"\n{result.stdout}" if result.stdout else ""
        if not merge_stderr and result.stderr:
            output += f"\n{result.stderr}"
        raise error_cls(f"{prefix} exited with status {result.returncode}{output}")
    return result

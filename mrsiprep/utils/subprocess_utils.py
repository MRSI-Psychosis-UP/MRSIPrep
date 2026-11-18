"""Shared subprocess execution helper for external-tool wrappers."""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 -- run_checked() below takes list args, never shell=True


def run_checked(
    cmd: list[str],
    *,
    verbose: bool = False,
    check: bool = True,
    merge_stderr: bool = False,
    env: dict | None = None,
    cpu_affinity: int | None = None,
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

    `cpu_affinity`, when given, pins `cmd` to that many CPUs via `taskset`
    (a hard OS-level scheduling cap). Some external tools (e.g. mri_synthseg,
    a PyTorch CPU workload) don't fully honor OMP_NUM_THREADS/MKL_NUM_THREADS
    for every internal thread pool they spin up even when both the env and
    the tool's own --threads flag are set, so they can still oversubscribe
    the host well past the requested thread budget; taskset caps actual
    core usage regardless of how many threads the child decides to spawn.
    Silently skipped if taskset isn't on PATH, since it's a performance cap,
    not correctness-affecting.
    """
    if cpu_affinity is not None and cpu_affinity > 0 and shutil.which("taskset"):
        cmd = ["taskset", "-c", f"0-{cpu_affinity - 1}", *cmd]
    # nosemgrep: dangerous-subprocess-use-audit,avoid-execution-of-untrusted-input-in-subprocess-calls
    # nosec B603 -- cmd is a list[str] from internal callers, no shell=True
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

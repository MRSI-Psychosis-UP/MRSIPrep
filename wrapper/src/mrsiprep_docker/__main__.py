#!/usr/bin/env python
"""
The *MRSIPrep* on Docker wrapper

A lightweight, dependency-free Python wrapper that builds and runs the
``docker run ...`` command for MRSIPrep, mirroring the fMRIPrep-on-Docker
wrapper's design. Docker must be installed and running (check with
``docker info``). Native ``mrsiprep`` arguments are passed straight through;
this wrapper only adds a handful of Docker-specific conveniences:

- translates ``bids_dir``/``output_dir``/``--fs-subjects-dir``/``--work-dir``
  into bind mounts,
- mounts ``--fs-license-file`` and sets ``FS_LICENSE``,
- passes the host timezone through (``-e TZ=...``) so container timestamps
  match the host clock,
- offers to pull the image if it isn't present locally,
- forwards HOST_UID/HOST_GID so output files land owned by the invoking user
  (see docker/entrypoint.sh in the main repository).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

try:
    from ._version import __version__
except ImportError:
    __version__ = "0+unknown"

__bugreports__ = "https://github.com/MRSI-Psychosis-UP/MRSIPrep/issues"

MISSING = """
Image '{}' is missing
Would you like to download? [Y/n] """


def check_docker() -> int:
    """-1 docker not found, 0 found but daemon unreachable, 1 OK."""
    try:
        ret = subprocess.run(["docker", "version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        from errno import ENOENT

        if exc.errno == ENOENT:
            return -1
        raise
    if ret.stderr.startswith(b"Cannot connect to the Docker daemon."):
        return 0
    return 1


def check_image(image: str) -> bool:
    ret = subprocess.run(["docker", "images", "-q", image], stdout=subprocess.PIPE)
    return bool(ret.stdout)


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MRSIPrep Docker wrapper: runs mrsiprep:cpu with the usual BIDS App syntax.",
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", help="show this help message")
    parser.add_argument("--version", action="store_true", help="show wrapper and image version")
    parser.add_argument("bids_dir", nargs="?", default="", help="the root folder of a BIDS dataset")
    parser.add_argument("output_dir", nargs="?", default="", help="the output derivatives directory")
    parser.add_argument("analysis_level", nargs="?", default="participant", choices=["participant"])

    g_wrap = parser.add_argument_group("Wrapper (Docker-only) options")
    g_wrap.add_argument("--image", default="fedlucchetti/mrsiprep:cpu", help="Docker image to use")
    g_wrap.add_argument("--fs-license-file", metavar="PATH", type=os.path.abspath, help="path to a FreeSurfer license.txt, mounted and exported as FS_LICENSE")
    g_wrap.add_argument("--fs-subjects-dir", metavar="PATH", type=os.path.abspath, help="existing FreeSurfer SUBJECTS_DIR to mount and reuse")
    g_wrap.add_argument("--work-dir", metavar="PATH", type=os.path.abspath, help="scratch directory, mounted at /scratch")
    g_wrap.add_argument("--participants", metavar="PATH", type=os.path.abspath, help="participants TSV/CSV, mounted read-only")
    g_wrap.add_argument("-u", "--user", help="run container as USER[:GROUP] instead of root (default: root, which self-chowns outputs to your user afterward)")
    g_wrap.add_argument("--no-tz", action="store_true", help="do not forward the host timezone to the container")
    g_wrap.add_argument("--shell", action="store_true", help="open a shell in the image instead of running mrsiprep")

    return parser


def main() -> int:
    parser = get_parser()
    opts, unknown_args = parser.parse_known_args()

    if (opts.bids_dir, opts.output_dir, opts.version, opts.help) == ("", "", False, False):
        opts.help = True

    check = check_docker()
    if check < 1:
        if opts.version:
            print(f"mrsiprep-docker wrapper {__version__}")
        if opts.help:
            parser.print_help()
        if check == -1:
            print("mrsiprep-docker: could not find the docker command. Is Docker installed?")
        else:
            print("mrsiprep-docker: make sure you have permission to run 'docker' (is the daemon running?)")
        return 1

    if not check_image(opts.image):
        resp = "Y"
        if opts.version:
            print(f"mrsiprep-docker wrapper {__version__}")
        if opts.help:
            parser.print_help()
        if opts.version or opts.help:
            try:
                resp = input(MISSING.format(opts.image))
            except KeyboardInterrupt:
                print()
                return 1
        if resp not in ("y", "Y", ""):
            return 0
        print("Downloading. This may take a while...")
        pull = subprocess.run(["docker", "pull", opts.image])
        if pull.returncode:
            return pull.returncode

    command = ["docker", "run", "--rm"]
    if sys.stdin.isatty() and sys.stdout.isatty():
        command.append("-it")

    # The container runs as root by default and chowns the output directory
    # back to its owner afterward (see docker/entrypoint.sh); pass -u only if
    # the caller explicitly asks, matching plain `docker run` behavior.
    if opts.user:
        command.extend(["-u", opts.user])
    else:
        command.extend(["-e", f"HOST_UID={os.getuid()}", "-e", f"HOST_GID={os.getgid()}"])

    if not opts.no_tz:
        tz_file = Path("/etc/timezone")
        if tz_file.exists():
            command.extend(["-e", f"TZ={tz_file.read_text().strip()}"])

    if opts.fs_license_file:
        command.extend(["-v", f"{opts.fs_license_file}:/opt/freesurfer/license.txt:ro", "-e", "FS_LICENSE=/opt/freesurfer/license.txt"])

    main_args: list[str] = []
    if opts.bids_dir:
        command.extend(["-v", f"{os.path.abspath(opts.bids_dir)}:/data:ro"])
        main_args.append("/data")
    if opts.output_dir:
        os.makedirs(opts.output_dir, exist_ok=True)
        command.extend(["-v", f"{os.path.abspath(opts.output_dir)}:/out"])
        main_args.append("/out")
    main_args.append(opts.analysis_level)

    if opts.fs_subjects_dir:
        command.extend(["-v", f"{opts.fs_subjects_dir}:/opt/subjects"])
        unknown_args.extend(["--fs-subjects-dir", "/opt/subjects"])

    if opts.work_dir:
        os.makedirs(opts.work_dir, exist_ok=True)
        command.extend(["-v", f"{opts.work_dir}:/scratch"])
        unknown_args.extend(["--work-dir", "/scratch"])

    if opts.participants:
        command.extend(["-v", f"{opts.participants}:/tmp/participants{Path(opts.participants).suffix}:ro"])
        unknown_args.extend(["--participants", f"/tmp/participants{Path(opts.participants).suffix}"])

    if opts.shell:
        command.append("--entrypoint=bash")

    command.append(opts.image)

    if opts.help:
        command.append("-h")
        target_help = subprocess.check_output(command).decode()
        print(parser.format_help())
        print("\n--- mrsiprep (inside the container) ---\n")
        print(target_help)
        return 0
    if opts.version:
        ret = subprocess.run([*command, "--version"])
        print(f"mrsiprep-docker wrapper {__version__}")
        return ret.returncode

    if not opts.shell:
        command.extend(main_args)
        command.extend(unknown_args)

    print("RUNNING: " + " ".join(command))
    ret = subprocess.run(command)
    if ret.returncode:
        print(f"MRSIPrep: please report errors to {__bugreports__}")
    return ret.returncode


if __name__ == "__main__":
    if "__main__.py" in sys.argv[0]:
        from . import __name__ as module

        sys.argv[0] = f"{sys.executable} -m {module}"
    sys.exit(main())

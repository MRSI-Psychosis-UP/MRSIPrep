# Installation

MRSIPrep is distributed as a Docker image. There is no supported host
installation of the pipeline itself — everything runs inside the container,
including its [Nipype](https://nipype.readthedocs.io/)-based workflow engine.

```bash
docker pull fedlucchetti/mrsiprep:cpu
```

The image bundles ANTs, FSL (FAST only), FreeSurfer (`recon-all`,
`mri_synthseg`, `mri_vol2vol`), PETPVC, Chimera, and Nipype. It does not
include a FreeSurfer license file — mount your own and set `FS_LICENSE`.

## Option A: plain `docker run`

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/bids/derivatives:/out \
  -v /path/to/freesurfer/license.txt:/opt/freesurfer/license.txt:ro \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  -e TZ="$(cat /etc/timezone)" \
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --mode mni-norm \
  --nthreads 8
```

The container runs as root and chowns the output directory back to its
existing owner after the run (see "Container internals" below) — no `-u`
flag is required. `-e TZ=...` keeps console/log timestamps in sync with the
host clock (the container defaults to UTC otherwise).

## Option B: the `mrsiprep-docker` wrapper (recommended)

A lightweight, dependency-free Python wrapper — mirroring fMRIPrep's
`fmriprep-docker` — is installable from PyPI and builds the `docker run`
command above for you:

```bash
pip install mrsiprep-docker

mrsiprep-docker /path/to/bids /path/to/bids/derivatives participant \
  --participant-label S001 --session-label V1 \
  --mode mni-norm --nthreads 8 \
  --fs-license-file /path/to/freesurfer/license.txt
```

Every ordinary `mrsiprep` argument (`--mode`, `--tissue-backend`, `--nproc`,
`--verbose`, ...) is passed straight through unchanged; the wrapper only
handles bind-mounting `--fs-license-file`, `--fs-subjects-dir`, `--work-dir`,
and `--participants`, and forwards the host timezone automatically. See the
[wrapper README](https://github.com/MRSI-Psychosis-UP/MRSIPrep/tree/main/wrapper)
for the full option list.

You will still need a BIDS dataset with already-quantified MRSI maps; see
[Basic Usage](usage_basic.md) for the full command-line walkthrough.

## Container internals

Two things run automatically inside the container on every invocation
(`docker/entrypoint.sh`), regardless of which option above you use:

- **Output ownership.** The container runs as root (required by some
  `recon-all`/ANTs/Chimera configurations) and afterward `chown`s the output
  directory back to `HOST_UID`/`HOST_GID` if set, or to the output
  directory's own existing owner otherwise — so files are never left
  root-owned on the host. Disable with `-e MRSIPREP_NO_FIXPERMS=1`, or pass
  `-u "$(id -u):$(id -g)"` (or `mrsiprep-docker -u ...`) to run as a non-root
  user from the start instead.
- **Timezone.** If `-e TZ=<zone>` is set, timestamps in the console, the
  per-recording logbook, and `mrsiprep_provenance.json` (see
  [Basic Usage](usage_basic.md)) match the host clock instead of defaulting
  to UTC.

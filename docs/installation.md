# Installation

MRSIPrep is distributed as a Docker image. There is no supported host
installation of the pipeline itself — everything runs inside the container,
including its [Nipype](https://nipype.readthedocs.io/)-based workflow engine.

```bash
docker pull mrsiup/mrsiprep:cpu
```

The image bundles ANTs, FSL (FAST plus FLIRT/FNIRT registration tools),
FreeSurfer (`recon-all`, `mri_synthseg`, `mri_vol2vol`), PETPVC, Chimera, and Nipype. It does not
include a FreeSurfer license file — mount your own and set `FS_LICENSE`.

## Option A: plain `docker run`

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/bids/derivatives:/out \
  -v /path/to/freesurfer/license.txt:/opt/freesurfer/license.txt:ro \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  -e TZ="$(cat /etc/timezone)" \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
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
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
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

## Minimum hardware requirements

| Resource | Minimum | Notes |
|---|---|---|
| RAM (Docker-allocated) | **8 GB** | Below this, `mri_synthseg` reliably crashes with `std::bad_alloc` / exit status `-9` (SIGKILL from the OOM killer) — confirmed reproducible with as little as 4 GB allocated to the Docker VM, and previously hit on GitHub Actions' standard 16 GB runners under concurrent `--nproc`. `--synthseg-mode fast` uses somewhat less memory than `robust` (the default) but is not a substitute for adequate RAM. |
| CPU cores | **4** | `recon-all` (parc-con + Chimera) and `mri_synthseg` are the most CPU-heavy steps; `--nthreads`/`--nproc` (see [Basic Usage](usage_basic.md)) should stay within the machine's actual core count — MRSIPrep coerces `--nthreads` down automatically if `nproc * nthreads` would exceed it. |
| Disk | A few GB per subject/session | Nipype's `--work-dir` cache (SynthSeg/FAST intermediates, resampled QC scratch maps) is the bulk of this; safe to delete between runs (see "The Nipype workflow engine" in [Basic Usage](usage_basic.md)). |

**On memory specifically**: if running multiple subjects concurrently
(`--nproc > 1`), each concurrent recording's `mri_synthseg`/`recon-all`
process needs its own share of RAM — the 8 GB minimum above is per
*concurrent* subject, not a fixed total. A batch run with `--nproc 4` should
have roughly `4 x 8 GB` = 32 GB available, not just 8 GB total, or reduce
`--nproc` instead. If you hit `mri_synthseg exited with status -9` or
`recon-all` disappearing mid-run with no other error, this is almost always
insufficient memory, not a data or configuration problem.

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

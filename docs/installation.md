# Installation

MRSIPrep is distributed as a Docker image. There is no supported host
installation of the pipeline itself: everything runs inside the container,
including its [Nipype](https://nipype.readthedocs.io/)-based workflow engine.

You will need Docker installed and running first; see the official
[Docker installation guide](https://docs.docker.com/get-started/get-docker/)
for instructions for your platform.

```bash
docker pull mrsiup/mrsiprep:cpu
```

The image bundles ANTs, FSL (FAST plus FLIRT/FNIRT registration tools),
FreeSurfer (`recon-all`, `mri_synthseg`, `mri_vol2vol`), PETPVC, Chimera, and Nipype. It does not
include a FreeSurfer license file. Mount your own and set `FS_LICENSE`.

## Verify the pull: `--hello-world`

No BIDS dataset or license file needed -- this just confirms the image was
pulled correctly and the container runs:

```bash
docker run --rm mrsiup/mrsiprep:cpu --hello-world
```

Prints the MRSIPrep banner and a confirmation message, then exits
immediately with status 0.

## Option A: the `mrsiprep-docker` wrapper (recommended)

A lightweight, dependency-free Python wrapper is installable from PyPI and builds the equivalent
`docker run` command for you:

```bash
pip install mrsiprep-docker

mrsiprep-docker /path/to/bids /path/to/bids/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --nthreads 8 \
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

## Option B: plain `docker run`

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
  --nthreads 8
```

The container runs as root and chowns the output directory back to its
existing owner after the run (see "Container internals" in
[Basic Usage](usage_basic.md)), no `-u` flag is required. `-e TZ=...` keeps
console/log timestamps in sync with the host clock (the container defaults
to UTC otherwise).

## Minimum hardware requirements

| Resource | Minimum | Notes |
|---|---|---|
| RAM (Docker-allocated) | **8 GB** | Below this, `mri_synthseg` reliably crashes with `std::bad_alloc` / exit status `-9` (SIGKILL from the OOM killer), confirmed reproducible with as little as 4 GB allocated to the Docker VM, and previously hit on GitHub Actions' standard 16 GB runners under concurrent `--nproc`. `--synthseg-mode fast` uses somewhat less memory than `robust` (the default) but is not a substitute for adequate RAM. |
| CPU cores | **4** | `recon-all` (with `--parcellation-mode chimera`) and `mri_synthseg` are the most CPU-heavy steps; `--nthreads`/`--nproc` (see [Basic Usage](usage_basic.md)) should stay within the machine's actual core count; MRSIPrep coerces `--nthreads` down automatically if `nproc * nthreads` would exceed it. |
| Disk | A few GB per subject/session | Nipype's `--work-dir` cache (SynthSeg/FAST intermediates, resampled QC scratch maps) is the bulk of this; safe to delete between runs (see "Caching and reruns" in [Basic Usage](usage_basic.md)). |

**On memory specifically**: if running multiple subjects concurrently
(`--nproc > 1`), each concurrent recording's `mri_synthseg`/`recon-all`
process needs its own share of RAM: the 8 GB minimum above is per
*concurrent* subject, not a fixed total. A batch run with `--nproc 4` should
have roughly `4 x 8 GB` = 32 GB available, not just 8 GB total, or reduce
`--nproc` instead. If you hit `mri_synthseg exited with status -9` or
`recon-all` disappearing mid-run with no other error, this is almost always
insufficient memory, not a data or configuration problem.

See "Container internals" in [Basic Usage](usage_basic.md) for what runs
automatically inside the container on every invocation (output-ownership
chown, timezone handling).

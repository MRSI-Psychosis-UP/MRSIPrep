# Installation

Install and start [Docker](https://docs.docker.com/get-started/get-docker/)
first. MRSIPrep's processing tools run inside its container.

## Install via the Docker wrapper

The default setup uses `mrsiprep-docker`, also used by commands generated
with the Command builder:

```bash
pip install mrsiprep-docker
mrsiprep-docker --help
```

`pip` installs the wrapper. If the image is missing, `--help` offers to
download it; accepting runs `docker pull mrsiup/mrsiprep:cpu`. An existing
local image is reused. Processing commands also pull a missing image
automatically.

## Verify the pull: `--hello-world`

Check that the container runs, without a dataset or licence:

```bash
docker run --rm mrsiup/mrsiprep:cpu --hello-world
```

A FreeSurfer licence is needed only for Chimera/`recon-all`; the default
SynthSeg workflow runs without one.

## Option A: Command builder (recommended)

Use the **Command builder** to configure a run in a browser form. Choose
your dataset, subjects, metabolites, and processing settings, then copy the
generated command into a terminal to run MRSIPrep.

With the wrapper installed above, install and launch the form:

```bash
pip install "mrsiprep[command-builder]"
mrsiprep-build-command
```

The command opens a local browser form. Docker must still be installed and
running; preprocessing runs in the container when you execute the generated
command. The form's options come from the same CLI definition as the
[argument reference](cli_reference.md).

1. Select your BIDS input and output directories using host paths. Include
   `derivatives/mrsi-orig/mrsinmrs.json`, or set `--mrsinmrs-file` to a custom
   acquisition metadata file.
2. Choose subjects/sessions, metabolites, and a reference metabolite.
3. Adjust processing settings, then copy the generated `mrsiprep-docker`
   command and run it in a terminal.
4. [Inspect the output and QC report](outputs.md) after processing.

See [Preparing inputs](inputs.md) for your own dataset, or follow
[First run](usage_basic.md) with the public demo dataset.

## Option B: the `mrsiprep-docker` wrapper

With the wrapper installed above, you can write a processing command
directly. The wrapper builds the equivalent `docker run` command and
downloads a missing image before starting the run:

```bash
mrsiprep-docker /path/to/bids /path/to/bids/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --nthreads 8
```

Every ordinary `mrsiprep` argument (`--tissue-backend`, `--nproc`,
`--verbose`, ...) is passed straight through unchanged; the wrapper only
handles bind-mounting `--fs-license-file`, `--fs-subjects-dir`, `--work-dir`,
`--participants`, and `--mrsinmrs-file`, and forwards the host timezone
automatically. See the
[wrapper README](https://github.com/MRSI-Psychosis-UP/MRSIPrep/tree/main/wrapper)
for the full option list.

You will still need a BIDS dataset with already-quantified MRSI maps; see
[Preparing inputs](inputs.md) and [First run](usage_basic.md).

## Option C: plain `docker run`

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/bids/derivatives:/out \
  -e TZ="$(cat /etc/timezone)" \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --nthreads 8
```

For Chimera, add `--fs-license-file /path/to/license.txt` to the wrapper.
With plain Docker, bind-mount the file at `/opt/freesurfer/license.txt` and
set `-e FS_LICENSE=/opt/freesurfer/license.txt`. See the
[parcellation guide](usage_parcellation.md#chimera-parcellation) for mode settings.

The container runs as root and chowns the output directory back to its
existing owner after the run (see "Container internals" in
[Batch runs, caching, and logs](running.md)), no `-u` flag is required. `-e TZ=...` keeps
console/log timestamps in sync with the host clock (the container defaults
to UTC otherwise).

## Minimum hardware requirements

| Resource | Minimum | Notes |
|---|---|---|
| RAM (Docker-allocated) | **8 GB** | Below this, `mri_synthseg` reliably crashes with `std::bad_alloc` / exit status `-9` (SIGKILL from the OOM killer), confirmed reproducible with as little as 4 GB allocated to the Docker VM, and previously hit on GitHub Actions' standard 16 GB runners under concurrent `--nproc`. `--synthseg-mode fast` uses somewhat less memory than `robust` (the default) but is not a substitute for adequate RAM. |
| CPU cores | **4** | `recon-all` (with `--parcellation-mode chimera`) and `mri_synthseg` are the most CPU-heavy steps; `--nthreads`/`--nproc` (see [Batch runs, caching, and logs](running.md)) should stay within the machine's actual core count; MRSIPrep coerces `--nthreads` down automatically if `nproc * nthreads` would exceed it. |
| Disk | A few GB per subject/session | Nipype's `--work-dir` cache (SynthSeg/FAST intermediates, resampled QC scratch maps) is the bulk of this; safe to delete between runs (see "Caching and reruns" in [Batch runs, caching, and logs](running.md)). |

**On memory specifically**: if running multiple subjects concurrently
(`--nproc > 1`), each concurrent recording's `mri_synthseg`/`recon-all`
process needs its own share of RAM: the 8 GB minimum above is per
*concurrent* subject, not a fixed total. A batch run with `--nproc 4` should
have roughly `4 x 8 GB` = 32 GB available, not just 8 GB total, or reduce
`--nproc` instead. If you hit `mri_synthseg exited with status -9` or
`recon-all` disappearing mid-run with no other error, this is almost always
insufficient memory, not a data or configuration problem.

See [Container internals](running.md#container-internals) in [Batch runs, caching, and logs](running.md) for what runs
automatically inside the container on every invocation (output-ownership
chown, timezone handling).

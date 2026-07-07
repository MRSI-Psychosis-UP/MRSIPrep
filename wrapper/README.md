# The *MRSIPrep* on Docker wrapper

MRSIPrep is distributed as a Docker image; there is no supported host
installation of the pipeline itself. This is a lightweight, dependency-free
Python wrapper (mirroring the `fmriprep-docker` wrapper) that builds and runs
the appropriate `docker run` command using the normal MRSIPrep BIDS App
syntax. Docker must be installed and running (check with `docker info`).

## Install

```bash
pip install mrsiprep-docker
```

## Use

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --mode mni-norm --nthreads 8 \
  --fs-license-file /path/to/freesurfer/license.txt
```

This generates and runs the equivalent of:

```bash
docker run --rm -it -u "$(id -u):$(id -g)" \
  -e TZ="$(cat /etc/timezone)" \
  -v /path/to/freesurfer/license.txt:/opt/freesurfer/license.txt:ro \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 --session-label V1 \
  --mode mni-norm --nthreads 8
```

All ordinary `mrsiprep` arguments (`--mode`, `--participant-label`,
`--tissue-backend`, `--parcellation-mode`, `--nproc`, `--verbose`, ...) are
passed straight through to the container unchanged. The wrapper only
special-cases the few options that need a bind mount or an environment
variable: `--fs-license-file`, `--fs-subjects-dir`, `--work-dir`, and
`--participants`.

`-u "$(id -u):$(id -g)"` (the default; override with `-u`/`--user`) plus the
container's own permission-fixing entrypoint means output files are owned by
the invoking user, not root. `-e TZ=...` (skip with `--no-tz`) keeps console
and logbook timestamps in sync with the host clock.

See the main repository's documentation for the full MRSIPrep CLI reference:
https://mrsiprep.readthedocs.io/

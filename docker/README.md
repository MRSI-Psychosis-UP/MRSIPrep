# Private Docker Build Workflow

MRSIPrep ships two runtime images:

```text
mrsiprep-deps:cpu  reduced private external/Python dependencies
mrsiprep:cpu       full application, including raw-to-Chimera support
```

## Image chain

Every build converges on the same tail. The only choice is how you produce the
unpruned source dependency image `mrsiprep-deps:ubuntu22.04-cpu`.

```text
ubuntu:22.04
  │
  ├─ (A) manual path                          ├─ (B) automated secret path
  │   Dockerfile.bootstrap                     │   Dockerfile.deps
  │     → mrsiprep-bootstrap:ubuntu22.04-cpu   │     → mrsiprep-deps:ubuntu22.04-cpu
  │   + manual FSL/FreeSurfer install          │
  │     → commit mrsiprep-deps:ubuntu22.04-cpu │
  │                                            │
  └──────────────┬─────────────────────────────┘
                 │  mrsiprep-deps:ubuntu22.04-cpu  (full, unpruned source deps)
                 ▼
        Dockerfile.cpu-deps  (prune + flatten)
                 → mrsiprep-deps:cpu
                 ▼
        Dockerfile  (thin MRSIPrep layer)
                 → mrsiprep:cpu
                 ▼
        docker/publish_image.sh
                 → fedlucchetti/mrsiprep:cpu
```

`mrsiprep-deps:ubuntu22.04-cpu` holds complete upstream installations. It is
flattened and reduced into `mrsiprep-deps:cpu`. Ordinary Python source changes
only require rebuilding the thin `mrsiprep:cpu` layer — see
[Python-only rebuilds](#python-only-rebuilds).

## Full rebuild from scratch → publish

Pick path **A** or **B** for the source dependency image, then run the shared
tail. End to end:

```bash
# --- Path A: manual FSL/FreeSurfer (recommended, less reproducible) ---
docker/build_bootstrap.sh          # → mrsiprep-bootstrap:ubuntu22.04-cpu
docker/enter_manual_deps.sh        # inside: bash /root/manual_install_fsl_freesurfer.sh && exit
docker/finalize_manual_deps.sh     # commit → mrsiprep-deps:ubuntu22.04-cpu

# --- OR Path B: automated secret-based build (more reproducible) ---
cp docker/private-neurodeps.env.example docker/private-neurodeps.env
# ...populate URLs/archive paths in the env file...
docker/build_private_deps.sh       # → mrsiprep-deps:ubuntu22.04-cpu

# --- Shared tail (both paths) ---
docker/build_cpu_image.sh          # prune → mrsiprep-deps:cpu, then build → mrsiprep:cpu
docker/test_container.sh mrsiprep:cpu
docker/publish_image.sh -r fedlucchetti/mrsiprep -t cpu
```

Each step is detailed below.

## Path A — manual FSL/FreeSurfer workflow

Build an Ubuntu 22.04 CPU bootstrap containing ANTs, ANTsPy, PETPVC, Chimera,
and the Python dependencies:

```bash
docker/build_bootstrap.sh
```

Enter a persistent named container:

```bash
docker/enter_manual_deps.sh
```

Inside it, install FSL and FreeSurfer using the provided helper or your own
commands:

```bash
bash /root/manual_install_fsl_freesurfer.sh
exit
```

The helper uses the official FSL `getfsl.sh` installer and the FreeSurfer 8.2.0
Ubuntu 22 package. You can override either URL with `FSL_INSTALLER_URL` or
`FREESURFER_DEB_URL` inside the container.

Commit and verify the private dependency image:

```bash
docker/finalize_manual_deps.sh
```

This commits the full, unpruned installation as `mrsiprep-deps:ubuntu22.04-cpu`.
Continue with the [shared tail](#shared-tail-prune-build-publish).

This manual path is private and convenient, but the resulting dependency image
is less reproducible than the automated secret-based build below.

## Path B — automated secret-based build

### 1. Configure private sources

```bash
cp docker/private-neurodeps.env.example docker/private-neurodeps.env
```

Populate the private file with download URLs:

```text
ANTS_URL=...
FSL_URL=...
FREESURFER_URL=...
PETPVC_URL=...
CHIMERA_URL=...
```

Alternatively set host archive paths such as:

```text
ANTS_ARCHIVE=/private/software/ants.tar.gz
FSL_ARCHIVE=/private/software/fsl.tar.gz
FREESURFER_ARCHIVE=/private/software/freesurfer.tar.gz
```

The configuration and archives are passed with BuildKit secrets. They are not
stored as Docker build arguments or copied into the final image.

### 2. Build private dependencies

```bash
docker/build_private_deps.sh
```

Configuration overrides:

```bash
DEPS_IMAGE=registry.private/mrsiprep-deps:2026-06 \
REQUIRE_PETPVC=1 \
REQUIRE_CHIMERA=1 \
docker/build_private_deps.sh
```

This builds `Dockerfile.deps`, produces `mrsiprep-deps:ubuntu22.04-cpu`, and
runs the dependency verifier automatically. Continue with the
[shared tail](#shared-tail-prune-build-publish).

## Shared tail (prune, build, publish)

### 3. Prune and build the full CPU image

Once `mrsiprep-deps:ubuntu22.04-cpu` exists (from path A or B):

```bash
docker/build_cpu_image.sh
```

This prunes and flattens the source deps into `mrsiprep-deps:cpu` (via
`Dockerfile.cpu-deps`), then automatically builds `mrsiprep:cpu` (via
`Dockerfile`). It keeps SynthSeg, FAST, ANTs, PETPVC, Chimera, `recon-all`, and
`mri_vol2vol`. FSL is reduced to FAST and its shared libraries. FreeSurfer is
trimmed conservatively while retaining its core reconstruction executables,
libraries, models, registration atlases, and `fsaverage` subject.

### 4. Test the images

```bash
docker/test_container.sh mrsiprep-deps:cpu
docker/test_container.sh mrsiprep:cpu
```

The check verifies the winning tissue tools, ANTsPy/ANTs CLI, Python imports,
and optionally PETPVC and Chimera/FreeSurfer commands.

### 5. Publish

Save a local tarball and/or push to Docker Hub:

```bash
docker/publish_image.sh -r fedlucchetti/mrsiprep -t cpu
```

Common variants:

```bash
docker/publish_image.sh --no-push                        # local ./dist tarball only
SKIP_SAVE=1 docker/publish_image.sh -r fedlucchetti/mrsiprep
```

Pushing requires `docker login` first. See `docker/publish_image.sh -h` for all
options.

## Python-only rebuilds

After changing MRSIPrep Python code only (no new dependencies):

```bash
docker/update_mrsiprep_image.sh
```

This rebuilds `Dockerfile`, which starts from the existing `mrsiprep-deps:cpu`
image and only copies/reinstalls MRSIPrep. It does not rebuild FreeSurfer, FSL,
ANTs, PETPVC, or Chimera. Follow with step 5 to republish.

Override image names when needed:

```bash
DEPS_IMAGE=registry.private/mrsiprep-deps:2026-06 \
APP_IMAGE=registry.private/mrsiprep:cpu \
docker/update_mrsiprep_image.sh
```

If `pyproject.toml` dependency requirements change, rebuild the dependency image
(path A or B) instead. Ordinary Python source changes only require this thin
update.

## Runtime license

FreeSurfer is installed in the private image, but its license is mounted at
runtime:

```bash
docker run --rm \
  -v /path/license.txt:/opt/freesurfer/license.txt:ro \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  -e TZ="$(cat /etc/timezone)" \
  mrsiprep:cpu /data /out participant
```

The container defaults to UTC regardless of the host's timezone, so console,
logbook, and provenance timestamps drift from host wall-clock time unless you
pass `-e TZ`. `$(cat /etc/timezone)` picks it up automatically on Linux; on
macOS/Windows pass the zone name directly (e.g. `-e TZ=Europe/Zurich`).

## Output permissions

The container runs as root, so files written into a bind-mounted output
directory would normally end up root-owned. The entrypoint chowns the output
tree back to the invoking host user after each run (defaulting to the output
directory's own existing owner, or override with `-e HOST_UID=$(id -u) -e
HOST_GID=$(id -g)`). Disable with `-e MRSIPREP_NO_FIXPERMS=1` if you manage
permissions yourself.

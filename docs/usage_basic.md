# Basic Usage

MRSIPrep runs as a Docker container; there is no supported host installation
of the pipeline itself. Either invoke `docker run` directly, or install the
[`mrsiprep-docker`](https://pypi.org/project/mrsiprep-docker/) wrapper from
PyPI (`pip install mrsiprep-docker`), which builds the equivalent `docker
run` command for you — see [Installation](installation.md) for both options.
The examples below use plain `docker run`; drop the bind-mount flags and
image name for the equivalent `mrsiprep-docker` command.

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --mode mni-norm \
  --synthseg-mode fast \
  --nthreads 8
```

`mni-norm` registers the imported MRSI signal maps to a SynthSeg-extracted
T1w image, resamples into MNI space, and runs SynthSeg with cortical
parcellation. Its parcel QC table reports the percentage of each anatomical
T1w parcel covered by MRSI, parcelwise CRLB, and valid-voxel fractions.
`mni-norm` does not run FAST, PETPVC, Chimera, or `recon-all`.

SynthSeg-based brain extraction always retains the whole brain (GM, WM,
ventricles, and inner/outer CSF, including extra-ventricular CSF label 24) —
only SynthSeg background (label 0) is excluded from the brain mask, so FAST
sees the complete CSF compartment when estimating tissue probabilities.

## Try it now: demo on the public SynthMRSI-Project dataset

No BIDS dataset of your own yet? Download the small, public, synthetic
**SynthMRSI-Project** dataset (32 subjects, real T1w + model-synthesized
MRSI signal, CC0) and run MRSIPrep against it directly:

```bash
# 1. Download and extract the public test dataset (~300-400MB)
curl -L -o SynthMRSI-Project.zip \
  "https://zenodo.org/records/21477048/files/SynthMRSI-Project.zip"
unzip SynthMRSI-Project.zip

# 2. Pull the CPU image
docker pull mrsiup/mrsiprep:cpu

# 3. Run a single subject in mni-norm mode (a couple of minutes on a
#    modern multi-core machine)
docker run --rm \
  -v "$(pwd)/SynthMRSI-Project:/data:ro" \
  -v "$(pwd)/SynthMRSI-Project/derivatives:/out" \
  -v /path/to/your/freesurfer/license.txt:/opt/freesurfer/license.txt:ro \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label 01 \
  --session-label 01 \
  --mode mni-norm \
  --t1 acq-mprage_T1w \
  --metabolites NAANAAG,GPCPCh,CrPCr,GluGln,Ins \
  --ref-met CrPCr \
  --nthreads 8 --nproc 2 --verbose 2

# 4. Open the QC report to confirm it worked
xdg-open SynthMRSI-Project/derivatives/mrsiprep/sub-01/ses-01/reports/coverage/sub-01_ses-01_desc-report.html
```

Drop `--participant-label 01` to process all 32 subjects (scale runtime by
`32 / --nproc`). You'll need a free FreeSurfer license file (from
https://surfer.nmr.mgh.harvard.edu/registration.html) for `mri_synthseg`.
See [PUBLIC_DATASET.md](https://github.com/MRSI-Psychosis-UP/MRSIPrep/blob/main/PUBLIC_DATASET.md)
in the repository for the dataset's full description, ground-truth files,
and expected output layout.

Check all selected subject/session inputs without running preprocessing:

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participants participants.tsv \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --validate-only
```

`--validate-only` reports every invalid recording before any expensive
segmentation, registration, parcellation, or PVC step starts. Use it before
starting an expensive batch run.

The preflight table shows, per recording: T1w reference, MRSI file count,
CRLB/SNR/FWHM quality map availability, brainmask, tissue files, a
FreeSurfer column (shown only in parc-con mode with Chimera parcellation,
indicating whether a valid prior `recon-all` output already exists and will
be reused), and the MRSI→T1/T1→MNI transform status.

## The Nipype workflow engine

Every processing run is orchestrated by a per-recording
[Nipype](https://nipype.readthedocs.io/) workflow
(`mrsiprep/workflows/nipype_engine/`) rather than a hand-rolled script. This
is transparent to normal use — the CLI, its arguments, and the console output
are unchanged — but it has two practical consequences:

- **Rerunning a completed subject/session skips already-finished steps.**
  Each of the 13 pipeline steps (tissue segmentation, anatomical prep, MRSI
  preprocessing, registration, tissue probability maps, PVC, resampling,
  SynthSeg parcellation/QC, Chimera/MNI parcellation, regional extraction,
  connectivity, metprofiles export, reports) is a cached Nipype node, keyed
  on the step name plus the full run configuration. If nothing about the
  configuration or the subject/session changed since a prior successful run,
  the step is skipped rather than recomputed — a rerun of an already-fully
  processed recording typically finishes in a few seconds instead of tens of
  minutes. Pass `--overwrite` (or one of the step-specific `--overwrite-*`
  flags) to force recomputation regardless of the cache.
- **`--nproc` fans out across recordings**, each running its own independent
  Nipype workflow; within one recording the steps run as a linear chain
  (they are an inherent data-dependency chain, not independently
  parallelizable).

The engine's own working files (node caches, intermediate SynthSeg/FAST
outputs, scratch resampled maps used only to build QC figures) live under
`--work-dir` (default `<output_dir>/work`), separate from the permanent
derivatives in `<output_dir>/mrsiprep/`. It is safe to delete `--work-dir`
between runs to reclaim space — the next run will simply recompute
everything from scratch (the permanent derivatives in `mrsiprep/` are
unaffected either way, though already-cached recordings will then rerun
since their node cache is gone).

## Verbosity, logging, and provenance

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participants participants.tsv \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --mode parc-con \
  --verbose 1 \
  --nthreads 8 \
  --nproc 4
```

`--verbose` (`0`-`3`, default `1`):

- `0` — only the start/finish line and elapsed time (hours-minutes, e.g.
  `0h06m`; seconds for sub-minute/cached runs) per subject/session.
- `1` — also prints each processing step as it starts (tissue segmentation,
  anatomical prep, MRSI preprocessing, registration, tissue maps, PVC,
  resampling, parcellation, regional extraction, connectivity, reports), with
  no per-step detail.
- `2` — also prints step-level detail (info/success/warning/error messages),
  including Chimera milestone markers (`processing supra-region: ...`,
  `starting cortical parcellation fusion`) so a single-threaded Chimera run —
  which can otherwise sit silently for 10-20+ minutes — shows visible
  progress.
- `3` — also lets ANTs, `recon-all`, and `mri_synthseg` print their own raw
  subprocess output instead of being captured, and prints the full traceback
  for a failed recording (at `0`-`2`, a failure shows only a one-line
  summary on console — the full traceback is always written to that
  recording's logbook regardless of `--verbose`, see below).

Every console line is timestamped `dd/mm-HH:MM`, e.g. `07/07-14:35 [ PROC ]
Tissue segmentation`; pass `-e TZ=<zone>` to the container (or let
`mrsiprep-docker` do it automatically) so these match the host clock instead
of the container's default UTC.

A full-detail DEBUG log is always written to
`<out>/mrsiprep/logs/mrsiprep_<timestamp>.log`, independent of the console
`--verbose` level.

### Per-recording logbook and provenance

Each subject/session additionally gets, inside its own output folder:

- `sub-*/ses-*/logs/sub-*_ses-*_desc-mrsiprep_log.txt` — every timestamped
  console message for that recording only, useful when re-reading a single
  subject's history out of a large batch run's combined log. If the
  recording fails, this logbook always contains the full exception text and
  traceback (an `ERROR`/`TRACE` entry), regardless of `--verbose` — the
  console itself only shows the full traceback at `--verbose 3`, to keep
  batch-run output readable at lower verbosity levels.
- `sub-*/ses-*/reports/sub-*_ses-*_desc-provenance.json` — the full run
  configuration, software versions, and a `pipeline_trace` array listing
  each of the 13 steps as `RAN` or `SKIPPED` with a one-line reason (e.g.
  `"mode=mni-norm, requires parc-con"`, `"--no-pvc"`, `"--write-connectivity
  not set"`). Because most steps are conditional on `--mode`,
  `--tissue-backend`, `--no-pvc`, and `--write-connectivity`, this is the
  authoritative record of what actually happened for a given recording,
  without having to re-derive it from the CLI flags used.

`--nproc` runs that many subject/session recordings concurrently; each one
gets `--nthreads` ANTs/ITK threads. MRSIPrep coerces `--nthreads` down (never
`--nproc`) if `nproc * nthreads` would exceed the host's CPU count, and shows
the resulting thread budget (or the coercion warning) in the preflight
summary before any recordings are processed — e.g. on a 32-core machine,
`--nproc 4 --nthreads 10` (40 threads) is coerced down to `--nthreads 8` (32
threads).

`mni-norm` requires `mri_synthseg` and ANTs. `parc-con` with the default
`synthseg-fast` tissue backend additionally requires FSL `fast`, PETPVC, and
(for Chimera parcellation) `recon-all` and a valid `FS_LICENSE`.

## Tissue backends (parc-con mode)

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --mode parc-con \
  --tissue-backend existing
```

The `existing` backend reuses precomputed CAT12 tissue maps and requires:

- a skull-stripped T1w derivative in `derivatives/skullstrip`,
- the raw BIDS T1w acquisition,
- a CAT12-style `p3` CSF probability map in `derivatives/cat12`.

If `p3` is missing, the recording fails. In batch processing, MRSIPrep logs
the error and continues with the next subject/session.

Disable tissue segmentation and PVC entirely with `--tissue-backend none`
(equivalent to also passing `--no-pvc`):

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --mode parc-con \
  --tissue-backend none
```

## Command-Line Arguments

```{argparse}
:module: mrsiprep.cli.parser
:func: build_parser
:prog: mrsiprep
```

By default, when a subject/session has more than one candidate raw T1w
acquisition, MRSIPrep picks one heuristically (preferring
`acq-memprage`/`mprage`/`mp2rage` and `run-01`). `--bids-filter-file` lets you
override that choice explicitly:

```json
{"t1w": {"acquisition": "memprage", "run": "01"}}
```

Only the `"t1w"` key is currently supported (any other top-level key is
rejected with an error rather than silently ignored). Filter values use
either MRSIPrep's short BIDS entity names (`acq`, `run`, `ses`, `sub`) or the
long PyBIDS-style names shown above (`acquisition`, `run`, `session`,
`subject`) interchangeably. A value of `null` requires the entity to be
absent from the filename.

See [MNI Normalization Usage](usage_normalization.md) for `--output-spaces`
and `--output-mrsi-t1w`, and
[Longitudinal (Subject-Template) Normalization](usage_longitudinal.md) for
`--longitudinal`.

## Output layout

```text
<out>/mrsiprep/sub-*/ses-*/mrsi/orig/          native/imported-grid MRSI signal maps
<out>/mrsiprep/sub-*/ses-*/mrsi/orig-pvc/      PVC-corrected native-grid maps
<out>/mrsiprep/sub-*/ses-*/mrsi/t1w/           T1w-aligned MRSI maps (opt-in, --output-mrsi-t1w)
<out>/mrsiprep/sub-*/ses-*/mrsi/mni/           MNI-normalized MRSI maps
<out>/mrsiprep/sub-*/ses-*/mrsi/parcel/        parc-con mode metabolite profile NPZ files
<out>/mrsiprep/sub-*/ses-*/anat/               raw T1w tissue files, brainCSF/registration inputs
<out>/mrsiprep/sub-*/ses-*/anat/synthseg/      SynthSeg brain/dseg outputs and parcelwise QC tables
<out>/mrsiprep/sub-*/ses-*/anat/tissue/        GM/WM/CSF tissue probsegs (T1w and MRSI space)
<out>/mrsiprep/sub-*/ses-*/qmasks/             QC, spike, and brain masks
<out>/mrsiprep/sub-*/ses-*/transforms/         ANTs MRSI→T1w and T1w→MNI transforms
<out>/mrsiprep/sub-*/ses-*/reports/coverage/   subject HTML report + parcelwise coverage/CRLB figures
<out>/mrsiprep/sub-*/ses-*/reports/qc-reports/ per-step QC HTML reports and figures
<out>/mrsiprep/sub-*/ses-*/reports/            provenance JSON (config, software versions, pipeline_trace)
<out>/mrsiprep/sub-*/ses-*/logs/                per-recording timestamped logbook
<out>/mrsiprep/logs/                           full-detail timestamped run logs (independent of --verbose)
<out>/chimera-atlases/sub-*/ses-*/anat/        raw Chimera atlas outputs (one scheme/scale per file)
<out>/work/                                    Nipype node cache and other scratch files (--work-dir)
```

## BIDS import utilities

These run on the host, not inside the container:

```bash
mrsiprep-import /source/folder /path/to/bids --subject S001 --session V1
mrsiprep-import-gui
```

The import helpers preserve the MRSI-Metabolic-Connectome derivative layout:
`derivatives/mrsi-orig`, `derivatives/cat12`, and `derivatives/skullstrip`.

## Limitations and scope

MRSIPrep is a BIDS App for whole-brain quantified MRSI derivatives, not a
general-purpose neuroimaging pipeline. In particular:

- It has no fieldmap/BOLD/functional-MRI handling — those are out of scope
  entirely, since the inputs are already-quantified MRSI metabolite maps
  rather than raw k-space or functional time series.
- Registration can use ANTs (default, rigid+affine+SyN) or FSL via
  `--registration-backend fsl` (FLIRT affine by default; add
  `--fsl-deformable` for an FNIRT deformable stage on the MRSI-to-T1w step);
  there is no TemplateFlow catalog, and normalization targets are limited to
  MNI152 (`MNI152NLin2009cAsym`) plus native T1w/MRSI space — see
  [MNI Normalization Usage](usage_normalization.md).
- `--longitudinal` builds one ANTs subject-template across sessions
  (requires `--registration-backend ants`) — see
  [Longitudinal (Subject-Template) Normalization](usage_longitudinal.md); it
  does not otherwise change per-session processing, and assumes reasonably
  stable anatomy across a subject's sessions.
- Chimera parcellation and the `synthseg-fast` tissue backend require
  FreeSurfer, FSL, and a valid `FS_LICENSE`; `mni-norm` mode does not.

## Troubleshooting

- Start with a full-detail run log at `<out>/mrsiprep/logs/mrsiprep_<timestamp>.log`,
  and the per-recording logbook at `sub-*/ses-*/logs/sub-*_ses-*_desc-mrsiprep_log.txt`
  for a single subject/session's history out of a larger batch (see
  "Verbosity, logging, and provenance" above).
- Re-run the same recording with `--verbose 2` (step-level detail) or
  `--verbose 3` (raw ANTs/`recon-all`/`mri_synthseg` subprocess output) to
  see exactly where a failure occurs.
- `--validate-only` checks all selected subject/session inputs before any
  expensive processing starts — run it first when troubleshooting a batch.
- `--check-external-libs` verifies required external binaries
  (ANTs/FSL/FreeSurfer/PETPVC/Chimera, as applicable to the selected mode)
  are present and exits.
- By default a batch run logs a recording's failure and continues with the
  rest; pass `--stop-on-first-crash` to abort immediately instead, which is
  often easier when debugging a single problematic recording.
- Report issues at
  [github.com/MRSI-Psychosis-UP/MRSIPrep/issues](https://github.com/MRSI-Psychosis-UP/MRSIPrep/issues).

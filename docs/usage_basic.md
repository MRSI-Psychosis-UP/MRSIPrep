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
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
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

Check all selected subject/session inputs without running preprocessing:

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participants participants.tsv \
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
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participants participants.tsv \
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
  subprocess output instead of being captured.

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
  subject's history out of a large batch run's combined log.
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
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
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
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --mode parc-con \
  --tissue-backend none
```

## Argument reference

### Subjects, sessions, and acquisitions

| Argument | Default | Description |
| --- | --- | --- |
| `--participant-label` | (all) | One or more subject labels to process, e.g. `S001 S002`. |
| `--session-label` | (all) | One or more session labels to process, e.g. `V1 V2`. |
| `--participants` | none | Path to a TSV/CSV with `subject`/`session` columns for batch runs, as an alternative to `--participant-label`/`--session-label`. |
| `--b0` | `3.0` | Field strength: `3.0` or `7.0`. Selects the default metabolite list when `--metabolites` is not given. |
| `--metabolites` | (B0-dependent list) | Metabolite names to process, e.g. `CrPCr GluGln GPCPCh NAANAAG Ins`. |
| `--t1` | `desc-brain_T1w` | BIDS filename pattern used to locate the input T1w image. |

### Quality thresholds

| Argument | Default | Description |
| --- | --- | --- |
| `--quality-metrics` | `snr linewidth crlb` | Which quality maps to check/report. |
| `--snr-min` | (package default) | Minimum acceptable SNR. |
| `--linewidth-max` | (package default) | Maximum acceptable linewidth/FWHM. |
| `--crlb-max` | (package default) | Maximum acceptable per-metabolite CRLB. |

### Processing mode and tissue segmentation

| Argument | Choices / Default | Description |
| --- | --- | --- |
| `--mode` (alias `--processing-mode`) | `mni-norm`, `parc-con` / `mni-norm` | `mni-norm`: SynthSeg extraction + parcellation only, no FAST/PVC/Chimera/`recon-all`. `parc-con`: adds tissue probability maps, PVC, and Chimera/MNI-atlas parcellation. |
| `--tissue-backend` | `synthseg-fast`, `existing`, `none` / `synthseg-fast` | How GM/WM/CSF probability maps are produced in parc-con mode. `synthseg-fast` segments with SynthSeg+FAST; `existing` reuses precomputed CAT12 maps from `derivatives/skullstrip`/`derivatives/cat12`; `none` disables tissue segmentation and PVC entirely. |
| `--synthseg-mode` | `fast`, `standard`, `robust` / `robust` | SynthSeg accuracy/speed trade-off; `fast` and `robust` are never combined. SynthSeg thread count is taken from `--nthreads`. |
| `--registration-t1-target` | `brain-csf`, `brain`, `raw` / `brain-csf` (parc-con mode), `brain` (mni-norm mode) | Which T1w variant MRSI is registered to. |
| `--csf-pv-threshold` | `0.95` | CSF partial-volume threshold used when building registration masks. |
| `--fs-subjects-dir` | none | Existing FreeSurfer `SUBJECTS_DIR` to reuse/write into (used by Chimera parcellation). |

### Filtering

| Argument | Default | Description |
| --- | --- | --- |
| `--no-filter` | off | Disable biharmonic spike-repair filtering of MRSI maps. |
| `--spikepc` | `99.0` | Percentile threshold used for spike detection. |
| `--no-pvc` | off | Disable partial-volume correction (parc-con mode only; always disabled in mni-norm mode). |

### Performance, logging, and control flow

| Argument | Default | Description |
| --- | --- | --- |
| `--nthreads` | `16` | ANTs/ITK thread count per subject/session process. |
| `--nproc` | `1` | Number of subject/session recordings to process in parallel (each its own Nipype workflow); combined with `--nthreads` this is capped at the host's CPU count. |
| `--verbose`, `-v` | `0`-`3` / `1` | Console output detail level (see above). |
| `--work-dir` | `<output_dir>/work` | Scratch directory for the Nipype node cache and other intermediate files; safe to delete between runs. |
| `--validate-only` | off | Check selected subject/session inputs and exit without processing. |
| `--check-external-libs` | off | Verify required external binaries are on `PATH`/installed and exit. |
| `--overwrite` | off | Force-rerun all steps, ignoring the Nipype node cache and any file-level cached outputs. |
| `--overwrite-filt` | off | Force-rerun MRSI filtering only. |
| `--overwrite-seg` | off | Force-rerun tissue segmentation (SynthSeg brain extraction + dseg/probseg) only. |
| `--overwrite-pve` | off | Force-rerun tissue probability map generation only. |
| `--overwrite-t1-reg` | off | Force-rerun MRSI→T1w registration only. |
| `--overwrite-mni-reg` | off | Force-rerun T1w→MNI registration only. |
| `--overwrite-transform` | off | Force-rerun transform resampling only. |
| `--overwrite-chimera` | off | Force re-run Chimera parcellation even if the output dseg file already exists. |

See [MNI Normalization Usage](usage_normalization.md) for `--output-spaces`
and `--output-mrsi-t1w`.

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

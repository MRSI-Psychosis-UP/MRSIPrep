# Basic Usage

MRSIPrep runs as a Docker container; there is no supported host installation
of the pipeline itself. Install the
[`mrsiprep-docker`](https://pypi.org/project/mrsiprep-docker/) wrapper
(`pip install mrsiprep-docker`), which builds and runs the equivalent
`docker run` command for you. See [Installation](installation.md) for
details.

A minimal run looks like this:

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr
```

This registers the imported MRSI signal maps to a SynthSeg-extracted T1w
image, resamples into MNI space, and parcellates with SynthSeg
cortical/subcortical labels -- the default `--parcellation-mode synthseg`
needs no Chimera and no `recon-all`/FreeSurfer licence.

## Command builder

Prefer a form over memorizing flags? `mrsiprep-build-command` launches a
local browser-based form (built with Streamlit) that assembles a runnable
`mrsiprep-docker` command for you to copy and run:

```bash
pip install "mrsiprep[command-builder]"
mrsiprep-build-command
```

It's generated directly from the CLI's own argument parser, so its fields
always match the real flag set. Options are grouped the same way as the
[Command-Line Arguments](cli_reference.md) reference, the generated command
updates live as you fill in the form, and selecting `--registration-backend`
only shows the ANTs- or FSL-specific options for that backend.

## Try it now: demo on the public SynthMRSI-Project dataset

No BIDS dataset of your own yet? Download the small, public, synthetic
**SynthMRSI-Project** dataset (32 subjects, real T1w + model-synthesized
MRSI signal, CC0) and run MRSIPrep against it directly:

```bash
# 1. Download and extract the public test dataset (~300-400MB)
curl -L -o SynthMRSI-Project.zip \
  "https://zenodo.org/records/22014466/files/SynthMRSI-Project.zip"
unzip SynthMRSI-Project.zip -d SynthMRSI-Project

# 2. Run a single subject with the default settings (a couple of minutes on a
#    modern multi-core machine)
mrsiprep-docker SynthMRSI-Project SynthMRSI-Project/derivatives participant \
  --participant-label 01 --session-label 01 \
  --t1 acq-mprage_T1w \
  --metabolites NAANAAG,GPCPCh,CrPCr,GluGln,Ins \
  --ref-met CrPCr \
  --nthreads 8 --nproc 1 --verbose 2

# 3. Open the QC report to confirm it worked
xdg-open SynthMRSI-Project/derivatives/mrsiprep/sub-01/ses-01/reports/sub-01_ses-01_desc-report.html
```

Drop `--participant-label 01` to process all 32 subjects (scale runtime by
`32 / --nproc`, and raise `--nproc` accordingly for batch runs). The default
`--parcellation-mode synthseg` does not require FreeSurfer, so no
`FS_LICENSE` is needed for this demo.
See [PUBLIC_DATASET.md](https://github.com/MRSI-Psychosis-UP/MRSIPrep/blob/main/PUBLIC_DATASET.md)
in the repository for the dataset's full description, ground-truth files,
and expected output layout.

## Verbosity, logging, and provenance

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participants participants.tsv \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --parcellation-mode chimera \
  --verbose 1 \
  --nthreads 8 \
  --nproc 4
```

`--verbose` (`0`-`3`, default `1`):

- `0`: only the start/finish line and elapsed time (hours-minutes, e.g.
  `0h06m`; seconds for sub-minute/cached runs) per subject/session.
- `1`: also prints each processing step as it starts (tissue segmentation,
  anatomical prep, MRSI preprocessing, registration, tissue maps, PVC,
  resampling, parcellation, regional extraction, connectivity, reports), with
  no per-step detail.
- `2`: also prints step-level detail (info/success/warning/error messages),
  including Chimera milestone markers (`processing supra-region: ...`,
  `starting cortical parcellation fusion`) so a single-threaded Chimera run
  (which can otherwise sit silently for 10-20+ minutes) shows visible
  progress.
- `3`: also lets ANTs, `recon-all`, and `mri_synthseg` print their own raw
  subprocess output instead of being captured, and prints the full traceback
  for a failed recording (at `0`-`2`, a failure shows only a one-line
  summary on console; the full traceback is always written to that
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

- `sub-*/ses-*/logs/sub-*_ses-*_desc-mrsiprep_log.txt`: every timestamped
  console message for that recording only, useful when re-reading a single
  subject's history out of a large batch run's combined log. If the
  recording fails, this logbook always contains the full exception text and
  traceback (an `ERROR`/`TRACE` entry), regardless of `--verbose`; the
  console itself only shows the full traceback at `--verbose 3`, to keep
  batch-run output readable at lower verbosity levels.
- `sub-*/ses-*/reports/sub-*_ses-*_desc-provenance.json`: the full run
  configuration, software versions, and a `pipeline_trace` array listing
  each step as `RAN` or `SKIPPED` with a one-line reason (e.g.
  `"parcellation_mode=synthseg, requires chimera or atlas"`, `"--no-pvc"`,
  `"--write-connectivity not set"`). Because several steps are conditional on
  `--parcellation-mode`, `--tissue-backend`, `--no-pvc`, and
  `--write-connectivity`, this is the
  authoritative record of what actually happened for a given recording,
  without having to re-derive it from the CLI flags used.

`--nproc` runs that many subject/session recordings concurrently; each one
gets `--nthreads` ANTs/ITK threads. MRSIPrep coerces `--nthreads` down (never
`--nproc`) if `nproc * nthreads` would exceed the host's CPU count, and shows
the resulting thread budget (or the coercion warning) in the preflight
summary before any recordings are processed, e.g. on a 32-core machine,
`--nproc 4 --nthreads 10` (40 threads) is coerced down to `--nthreads 8` (32
threads).

Every run requires `mri_synthseg` and ANTs. The default `synthseg-fast`
tissue backend additionally requires FSL `fast`, and PVC requires PETPVC;
`--parcellation-mode chimera` also needs `recon-all` and a valid
`FS_LICENSE`. `--check-external-libs` reports exactly which binaries the
current configuration needs and whether they were found.

## Caching and reruns

Every processing run is orchestrated by a per-recording
[Nipype](https://nipype.readthedocs.io/) workflow
(`mrsiprep/workflows/nipype_engine/`) rather than a hand-rolled script. This
is transparent to normal use (the CLI, its arguments, and the console output
are unchanged) but it has two practical consequences:

- **Rerunning a completed subject/session skips already-finished steps.**
  Each of the 16 pipeline steps (input preparation, tissue segmentation,
  anatomical prep, MRSI preprocessing, registration, tissue probability maps,
  tissue QC, PVC, resampling, leakage QC, SynthSeg parcellation/QC,
  Chimera/atlas parcellation, regional extraction, connectivity, metprofiles
  export, reports) is a cached Nipype node, keyed
  on the step name plus the full run configuration. If nothing about the
  configuration or the subject/session changed since a prior successful run,
  the step is skipped rather than recomputed: a rerun of an already-fully
  processed recording typically finishes in a few seconds instead of tens of
  minutes.
- **`--nproc` fans out across recordings**, each running its own independent
  Nipype workflow; within one recording the steps run as a linear chain
  (they are an inherent data-dependency chain, not independently
  parallelizable).

The engine's own working files (node caches, intermediate SynthSeg/FAST
outputs, scratch resampled maps used only to build QC figures) live under
`--work-dir` (default `<output_dir>/work`), separate from the permanent
derivatives in `<output_dir>/mrsiprep/`. It is safe to delete `--work-dir`
between runs to reclaim space: the next run will simply recompute
everything from scratch (the permanent derivatives in `mrsiprep/` are
unaffected either way, though already-cached recordings will then rerun
since their node cache is gone).

**Force recomputation.** Pass `--overwrite` to ignore the cache entirely, or
one of the step-specific flags to force just one stage while leaving every
other cached stage untouched: `--overwrite-filt` (spike filtering),
`--overwrite-seg` (tissue segmentation), `--overwrite-pve` (partial-volume
correction), `--overwrite-t1corr` (T1 saturation correction),
`--overwrite-t1-reg`/`--overwrite-template-reg` (registration transforms),
`--overwrite-transform` (resampling through existing transforms), or
`--overwrite-chimera` (Chimera parcellation). For example, to force SynthSeg
to recompute after changing `--synthseg-mode`, without discarding every
other cached stage:

```bash
mrsiprep-docker /path/to/bids /path/to/out participant \
  --participant-label 01 --session-label 01 \
  --metabolites CrPCr,NAANAAG --ref-met CrPCr \
  --overwrite-seg
```

**Check inputs before a batch run.** `--validate-only` reports every
invalid recording before any expensive segmentation, registration,
parcellation, or PVC step starts, via a preflight table (T1w reference,
MRSI file count, quality-map availability, transform status, and so on):

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participants participants.tsv \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --validate-only
```

**Rebuild just the report.** `--reports-only` reuses every already-completed
step's output derivatives as-is and only regenerates QC tables, figures, and
`desc-report.html` -- useful after updating MRSIPrep to pick up a
report-only change without rerunning SynthSeg/ANTs/Chimera. It fails a
recording with a clear error (rather than silently recomputing) if a
required upstream derivative is missing, so it is not a substitute for a
normal run on unprocessed data:

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --reports-only
```

## Tissue backends

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --parcellation-mode chimera \
  --tissue-backend existing
```

The `existing` backend reuses precomputed CAT12 tissue maps and requires:

- a skull-stripped T1w derivative in `derivatives/skullstrip`,
- the raw BIDS T1w acquisition,
- CAT12-style `p1` (gray matter), `p2` (white matter), and `p3` (CSF)
  probability maps in `derivatives/cat12`, named
  `sub-<label>[_ses-<label>]_desc-p{1,2,3}_T1w.nii[.gz]`.

There is no CLI flag to point at a different location -- MRSIPrep discovers
these purely by the BIDS-derivatives directory/filename convention above.
If any of `p1`, `p2`, or `p3` is missing, the recording fails. In batch
processing, MRSIPrep logs the error and continues with the next
subject/session.

Disable tissue segmentation and PVC entirely with `--tissue-backend none`
(equivalent to also passing `--no-pvc`):

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --parcellation-mode chimera \
  --tissue-backend none
```

## Spike filtering

Raw quantified metabolite maps can contain spurious, high-amplitude voxel
clusters (fit instability, motion, spectral artifacts) that are not genuine
metabolic signal. By default MRSIPrep detects and repairs these (median
filtering + biharmonic inpainting) before any other stage uses the map.
Disable it entirely with `--no-filter`, e.g. when validating against data
you already know is spike-free and want to skip the extra processing time:

```bash
  --no-filter
```

The repaired region is smoothed back into its surroundings with a
Gaussian of width `--filter-fwhm-mm` (default: derived from the native
MRSI voxel size, mean voxel dimension $\times\sqrt{2}$). Override it
directly if the default over- or under-smooths a repaired cluster relative
to your acquisition's native resolution:

```bash
  --filter-fwhm-mm 6.0
```

## CSF partial-volume threshold

When `--registration-t1-target brain-csf` is used (adding CSF back into the
otherwise skull-stripped T1w registration target, so CSF-contaminated MRSI
signal near the ventricles doesn't register as if it fell entirely outside
the brain), `--csf-pv-threshold` sets how confident the CAT12 CSF
probability map must be before a voxel is added back:

```bash
  --registration-t1-target brain-csf --csf-pv-threshold 0.5
```

Lower it to include more borderline-CSF voxels in the registration target;
raise it (default `0.95`) to keep the target closer to a strict brain mask.

## MRSI orientation correction

Post-quantification MRSI maps occasionally come out of the vendor/quantification
pipeline with a wrong sform/qform -- close enough to plausible that spike
filtering, PVC, and even MRSI-to-T1w registration all "succeed", but the whole
recording ends up subtly or badly misaligned. `--correct-mrsi-orientation`
fixes this upstream of everything else: before any MRSI preprocessing runs, it
does a quick rigid-only registration of the reference metabolite map (`--ref-met`)
to the T1w anatomical, then applies that same rigid correction to every other
metabolite/CRLB/SNR/FWHM map, in place, at native MRSI resolution (shape and
voxel spacing are unchanged; only position/orientation is corrected).

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --correct-mrsi-orientation
```

Off by default -- most recordings do not need it, and the real (deformable)
MRSI-to-T1w registration that runs afterward already tolerates ordinary
misalignment. Uses `--registration-backend` (ANTs `Rigid`, or FLIRT `dof=6`
for `fsl`).

See [Command-Line Arguments](cli_reference.md) for the full flag reference,
including `--bids-filter-file` for disambiguating multiple candidate raw T1w
acquisitions.

## Output layout

```text
<out>/mrsiprep/sub-*/ses-*/mrsi/orig/          native/imported-grid MRSI signal maps only
<out>/mrsiprep/sub-*/ses-*/mrsi/orig-t1corr/   T1-saturation-corrected native-grid signal maps
                                                (opt-in, --t1-correction literature)
<out>/mrsiprep/sub-*/ses-*/mrsi/orig-pvc/      PVC-corrected native-grid signal maps only
<out>/mrsiprep/sub-*/ses-*/mrsi/t1w/           T1w-aligned MRSI signal maps only (opt-in, --output-mrsi-t1w)
<out>/mrsiprep/sub-*/ses-*/mrsi/mni/           MNI-normalized MRSI signal maps only
<out>/mrsiprep/sub-*/ses-*/mrsi/parcel/        per-parcel metabolite profile NPZ files
<out>/mrsiprep/sub-*/ses-*/anat/synthseg/      SynthSeg brain/dseg outputs, brainCSF/registration inputs,
                                                and parcelwise QC tables
<out>/mrsiprep/sub-*/ses-*/confounds/          every quantity that encodes a preprocessing assumption
                                                rather than signal itself, one file per space/metabolite
                                                (space-* entity in the filename): CRLB, SNR, FWHM/linewidth,
                                                spike masks, QC masks, brain mask, GM/WM/CSF tissue probsegs,
                                                T1-correction summary (opt-in, --t1-correction literature),
                                                per-metabolite signal leakage summary (desc-leakageqc)
<out>/mrsiprep/sub-*/ses-*/transforms/         ANTs MRSI→T1w and T1w→MNI transforms
<out>/mrsiprep/sub-*/ses-*/reports/             combined subject HTML report (desc-report.html), all QC
                                                figures (reports/figures/), parcelwise coverage/CRLB figures,
                                                per-metabolite signal leakage table, provenance JSON (config,
                                                software versions, pipeline_trace), and runtime metrics JSON
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

See [Limitations and scope](limitations.md) for what MRSIPrep does not
cover, and [Troubleshooting](troubleshooting.md) for diagnosing a failed or
unexpected run.

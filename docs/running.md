# Batch runs, caching, and logs

Run and monitor a cohort after completing the [first-run tutorial](usage_basic.md).
See [Installation](installation.md) for the memory needed per concurrent recording.

## Select recordings and resources

Omitting participant/session filters processes the discovered recordings.
Use `--participant-label 01 02` and `--session-label 01 02` for subsets, or
pass `--participants /path/to/recordings.tsv` with one recording per row:

```text
participant_id	session_id
sub-01	ses-01
sub-02	ses-01
```

For sessionless data, leave the session field empty. The wrapper mounts a
participants file supplied on the host. Without an explicit participants
file, a BIDS-root `participants_allsessions.tsv` is used when present;
otherwise recording discovery follows the subject/session directories.
Check the selected rows with `--validate-only` before starting a batch.

`--nproc` is the number of concurrent recordings, and `--nthreads` sets
the per-recording thread budget. Allow roughly 8 GB of memory per concurrent
recording as a starting minimum, with more for demanding anatomical inputs.
Keep `nproc * nthreads` within available CPU resources. The
[runtime benchmark](benchmarks.md) illustrates why increasing batch
concurrency can be more useful than allocating many threads to one recording.

## Verbosity, logging, and provenance

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participants participants.tsv \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
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
  record of the resolved configuration and configured stage gating.
  The trace is configuration-derived; use logs and runtime metrics to
  determine execution and cache history.

`--nproc` runs that many subject/session recordings concurrently; each one
gets `--nthreads` ANTs/ITK threads. MRSIPrep coerces `--nthreads` down (never
`--nproc`) if `nproc * nthreads` would exceed the host's CPU count, and shows
the resulting thread budget (or the coercion warning) in the preflight
summary before any recordings are processed, e.g. on a 32-core machine,
`--nproc 4 --nthreads 10` (40 threads) is coerced down to `--nthreads 8` (32
threads).

Required binaries depend on the selected configuration. The container
bundles the supported toolchains; `--check-external-libs` reports which
binaries the current configuration needs and whether they were found.
Chimera additionally needs `recon-all` and a valid `FS_LICENSE`.


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


## Container internals

Two things run automatically inside the container on every invocation
(`docker/entrypoint.sh`), regardless of whether you use the
`mrsiprep-docker` wrapper or a plain `docker run` (see
[Installation](installation.md)):

- **Output ownership.** The container runs as root (required by some
  `recon-all`/ANTs/Chimera configurations) and afterward `chown`s the output
  directory back to `HOST_UID`/`HOST_GID` if set, or to the output
  directory's own existing owner otherwise, so files are never left
  root-owned on the host. Disable with `-e MRSIPREP_NO_FIXPERMS=1`, or pass
  `-u "$(id -u):$(id -g)"` (or `mrsiprep-docker -u ...`) to run as a non-root
  user from the start instead.
- **Timezone.** If `-e TZ=<zone>` is set, timestamps in the console, the
  per-recording logbook, and `mrsiprep_provenance.json` (see below) match
  the host clock instead of defaulting to UTC.

# MNI Normalization Usage

MRSIPrep registers MRSI maps to T1w space with ANTs and, optionally,
normalizes them further into MNI space.

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --mode mni-norm \
  --output-spaces T1w MNI152NLin2009cAsym \
  --mni-resolution t1wres \
  --nthreads 16
```

`--output-spaces` selects which space(s) the final MRSI maps are resampled
into: `MRSI`, `T1w`, `MNI152NLin2009cAsym` (aliases `mrsi`, `t1`, `mni`
accepted). `--mni-resolution` selects the MNI template resolution used for
both T1w→MNI registration and final resampling: `origres` (MRSI native
resolution), `t1wres` (T1w resolution, default), or an explicit `<N>mm`.

CRLB, SNR, and FWHM(linewidth) maps for the configured `--metabolites` are
transformed into T1w/MNI space alongside the signal maps whenever present;
per-metabolite spike masks are only transformed if `--transform-spikemask`
is passed (the combined QC mask stays in MRSI space).

## ANTs-SyN normalization

`--normalization` controls the T1w→MNI strategy. The default `simple` path
uses a fast affine fit; `ants-syn` runs a full deformable SyN registration
for higher anatomical accuracy at additional compute cost:

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --mode parc-con \
  --normalization ants-syn \
  --output-spaces MNI152NLin2009cAsym \
  --nthreads 16
```

`existing` reuses a precomputed transform instead of registering — useful
when a T1w→MNI transform was already produced by a prior run or an external
pipeline.

## Argument reference

| Argument | Choices / Default | Description |
| --- | --- | --- |
| `--registration-backend` | `ants` / `ants` | Registration engine (currently only ANTs). |
| `--normalization` | `simple`, `ants-syn`, `existing` / `simple` | T1w→MNI normalization strategy; `existing` reuses a precomputed transform instead of registering. |
| `--output-spaces` | `T1w MNI152NLin2009cAsym` | Which space(s) to resample final MRSI maps into: `MRSI`, `T1w`, `MNI152NLin2009cAsym` (aliases `mrsi`, `t1`, `mni` accepted). |
| `--mni-resolution` | `origres`, `t1wres`, `<N>mm` / `t1wres` | MNI template resolution for both T1w→MNI registration and final resampling. |
| `--ref-met` | `CrPCr` | Reference metabolite map used to build the MRSI registration target. |
| `--registration-t1-target` | `brain-csf`, `brain`, `raw` / `brain-csf` (parc-con mode), `brain` (mni-norm mode) | Which T1w variant MRSI is registered to. |
| `--transform-spikemask` | off | Also transform per-metabolite spike masks into T1w/MNI space (the combined QC mask is never transformed). |
| `--transform` | `""` | Legacy output-transform override; prefer `--output-spaces`. |
| `--overwrite-t1-reg` | off | Force-rerun MRSI→T1w registration only. |
| `--overwrite-mni-reg` | off | Force-rerun T1w→MNI registration only. |
| `--overwrite-transform` | off | Force-rerun transform resampling only. |

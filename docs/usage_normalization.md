# MNI Normalization Usage

MRSIPrep registers MRSI maps to T1w space with ANTs and, optionally,
normalizes them further into MNI space.

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
  --output-spaces MNI152NLin2009cAsym \
  --mni-resolution origres \
  --nthreads 16
```

`--output-spaces` (default `MNI152NLin2009cAsym` only) selects which
space(s) the final MRSI maps are resampled into as permanent derivatives:
`MRSI`, `MNI152NLin2009cAsym` (aliases `mrsi`, `mni` accepted). `--mni-resolution`
selects the MNI template resolution used for both T1w→MNI registration and
final resampling: `origres` (MRSI native resolution, **default**, avoids
implying spatial precision the MRSI acquisition never had, and matches the
resolution mrsiprep's own spatial-smoothness benchmark evaluates at),
`t1wres` (T1w resolution), or an explicit `<N>mm`. In `--longitudinal`
mode, the shared subject-template-to-MNI registration stage always uses
`t1wres` regardless of this flag, since the template spans multiple
sessions that may have different native MRSI resolutions and there is no
single well-defined "native" choice there; per-session outputs are
unaffected.

T1w-space resampling of every metabolite (+ CRLB/SNR/FWHM/spikemask) is
**opt-in** via `--output-mrsi-t1w`, since nothing downstream (regional
extraction, connectivity, metprofiles) consumes it; only the
registration-overview QC report needs one reference-metabolite map in T1w
space, and it generates that itself into `--work-dir` regardless of this
flag, so the QC figure is always available even without `--output-mrsi-t1w`:

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
  --output-mrsi-t1w \
  --nthreads 16
```

With `--output-mrsi-t1w`, the full per-metabolite T1w-space maps are written
to `<out>/mrsiprep/sub-*/ses-*/mrsi/t1w/` as permanent derivatives.

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
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --mode parc-con \
  --normalization ants-syn \
  --output-spaces MNI152NLin2009cAsym \
  --nthreads 16
```

`existing` reuses a precomputed transform instead of registering, useful
when a T1w→MNI transform was already produced by a prior run or an external
pipeline.

See [Longitudinal (Subject-Template) Normalization](usage_longitudinal.md)
for `--longitudinal`, which registers one unbiased ANTs template built
across a subject's sessions to MNI instead of registering each session
directly.

See [Basic Usage](usage_basic.md) for the full CLI
reference, including `--registration-backend`, `--normalization`,
`--output-spaces`, `--output-mrsi-t1w`, `--mni-resolution`, `--ref-met`,
`--registration-t1-target`, `--transform-spikemask`, `--overwrite-t1-reg`,
`--overwrite-mni-reg`, and `--overwrite-transform`.

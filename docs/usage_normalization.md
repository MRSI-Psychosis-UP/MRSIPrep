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
  --mni-resolution t1wres \
  --nthreads 16
```

`--output-spaces` (default `MNI152NLin2009cAsym` only) selects which
space(s) the final MRSI maps are resampled into as permanent derivatives:
`MRSI`, `MNI152NLin2009cAsym` (aliases `mrsi`, `mni` accepted). `--mni-resolution`
selects the MNI template resolution used for both T1w→MNI registration and
final resampling: `origres` (MRSI native resolution), `t1wres` (T1w
resolution, default), or an explicit `<N>mm`.

T1w-space resampling of every metabolite (+ CRLB/SNR/FWHM/spikemask) is
**opt-in** via `--output-mrsi-t1w`, since nothing downstream (regional
extraction, connectivity, metprofiles) consumes it — only the
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

`existing` reuses a precomputed transform instead of registering — useful
when a T1w→MNI transform was already produced by a prior run or an external
pipeline.

## Longitudinal (subject-template) normalization

Requires `--registration-backend ants` (the default).

For subjects scanned across multiple sessions, `--longitudinal` builds one
unbiased ANTs template across all of that subject's sessions and registers
the template to MNI once, instead of registering each session directly to
MNI independently. Every session's final MNI-space maps are then produced by
composing (session→template) with (template→MNI), reducing registration
noise/bias across timepoints — the same "custom template" concept used by
fMRIPrep's longitudinal processing.

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 V2 V3 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --mode mni-norm \
  --longitudinal \
  --nthreads 16
```

The template is built with `antsMultivariateTemplateConstruction2.sh`
(4 iterations, rigid initial alignment) and registered to MNI with
`antsRegistrationSyN.sh -t s` (full SyN), mirroring the longitudinal
normalization already validated in the MRSI-Metabolic-Connectome research
pipeline. It runs once per subject, before any session's own processing, and
is cached the same way as every other registration stage — reruns skip it
unless `--overwrite`/`--overwrite-mni-reg` is passed or a session is added.

**Single-session subjects are unaffected.** `--longitudinal` is a no-op for
any subject with only one ready session; that session falls back to direct
per-session T1w→MNI registration as usual.

Derivatives are written per subject (not per session):

```text
sub-<label>/ses-all/transforms/anat/
  sub-<label>_ses-all_desc-template_to_mni.affine.mat
  sub-<label>_ses-all_desc-template_to_mni.syn.nii.gz
sub-<label>/ses-<session>/transforms/anat/
  sub-<label>_ses-<session>_desc-t1w_to_template.affine.mat
  sub-<label>_ses-<session>_desc-t1w_to_template.syn.nii.gz
```

See [Basic Usage](usage_basic.md) for the full CLI
reference, including `--registration-backend`, `--normalization`,
`--output-spaces`, `--output-mrsi-t1w`, `--mni-resolution`, `--ref-met`,
`--registration-t1-target`, `--transform-spikemask`, `--overwrite-t1-reg`,
`--overwrite-mni-reg`, `--overwrite-transform`, and `--longitudinal`.

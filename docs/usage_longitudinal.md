# Longitudinal (Subject-Template) Normalization

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

This mode requires `--registration-backend ants` (the default); it is
rejected at startup when combined with `--registration-backend fsl`/
`flirt-fnirt`, since the FSL backend has no equivalent subject-template
construction step.

## Algorithm

1. **Subject template construction.** For every subject with two or more
   ready sessions, all of that subject's session T1w reference images
   (the same `registration_t1w` each session already registers MRSI onto)
   are fed to `antsMultivariateTemplateConstruction2.sh -d 3 -i 4 -g 0.2 -k 1
   -r 1` — 4 iterations, rigid initial alignment — producing one unbiased
   template image plus a (session→template) transform for every input
   session. This mirrors the longitudinal normalization already validated in
   the MRSI-Metabolic-Connectome research pipeline
   (`registration_multivisit.sh`).
2. **Template→MNI registration.** The resulting subject template is
   registered to the MNI152 template once with `antsRegistrationSyN.sh -t s`
   (full deformable SyN).
3. **Composition.** Each session's final MNI-space maps are produced by
   composing that session's (session→template) transform with the single
   (template→MNI) transform, instead of registering the session directly to
   MNI. The composed forward-transform list is applied with the same
   `antsApplyTransforms`/antspyx machinery used everywhere else in MRSIPrep —
   no new transform file format.

Single-session subjects are unaffected: `--longitudinal` is a no-op for any
subject with only one ready session, and that session falls back to direct
per-session T1w→MNI registration as usual.

## Execution order and caching

The subject template is built **once per subject**, in a pre-pass before any
of that subject's individual session recordings are dispatched to the Nipype
engine — so every session's per-recording workflow can be seeded with its
subject's already-built template instead of re-deriving it. Building the
template itself requires each session's tissue segmentation and anatomical
preparation to have already run (to obtain each session's `registration_t1w`
reference), so those two steps execute for every session up front as part of
this pre-pass, ahead of the rest of that session's pipeline.

The template and its MNI registration are cached the same way as every other
registration stage in MRSIPrep: on a rerun, if the subject template image and
every expected transform file already exist on disk, the whole
construction+registration step is skipped. Pass `--overwrite` or
`--overwrite-mni-reg` to force it to rerun (e.g. after adding a new session
for a subject that was previously built with fewer sessions).

`--verbose 1` and above show a `Building subject template (sub-<label>, N
sessions)` step, once per subject, before that subject's first session
starts.

## Derivatives

Outputs are written per subject as well as per session — the template and
its MNI registration live under a subject-level `ses-all` transform
directory, while each session keeps only its (session→template) transform:

```text
sub-<label>/ses-all/transforms/anat/
  sub-<label>_ses-all_desc-template_to_mni.affine.mat
  sub-<label>_ses-all_desc-template_to_mni.affine_inv.mat
  sub-<label>_ses-all_desc-template_to_mni.syn.nii.gz
  sub-<label>_ses-all_desc-template_to_mni.syn_inv.nii.gz
sub-<label>/ses-<session>/transforms/anat/
  sub-<label>_ses-<session>_desc-t1w_to_template.affine.mat
  sub-<label>_ses-<session>_desc-t1w_to_template.syn.nii.gz
```

Every other derivative (final MNI-space MRSI maps, QC reports, parcellation,
regional extraction) is written in exactly the same location and naming
convention as a non-longitudinal run — `--longitudinal` only changes how the
T1w→MNI transform is produced, not where or how anything downstream is
stored.

## Preflight status

`--validate-only` shows an additional `Ses→Template` column (alongside the
usual `MRSI→T1` and `T1→MNI` columns) when `--longitudinal` is set, reporting
whether each session's (session→template) transform already exists on disk.

See [Basic Usage](usage_basic.md) for the full CLI reference, and
[MNI Normalization Usage](usage_normalization.md) for the non-longitudinal
(direct per-session) T1w→MNI registration options
(`--normalization`, `--output-spaces`, `--output-mrsi-t1w`,
`--mni-resolution`, `--registration-t1-target`).

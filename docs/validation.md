# Validation overview

MRSIPrep's benchmarks address different questions. Read their datasets,
configurations, and limitations before transferring a result to a new
acquisition or analysis.

| Benchmark | Question | Evidence and scope |
|---|---|---|
| [Runtime](benchmarks.md) | How do thread count and image resolution affect elapsed time? | One 3T and one 7T subject on the reported workstation; fresh caches and isolated runs. |
| [Registration](registration_benchmark.md) | How do the tested transforms affect signal leakage and anatomical overlays? | The same two subjects, four registration configurations, and two anatomical targets; timing scope differs for the affine ANTs comparison. |
| [Voxel-based detection](vba_benchmark.md) | Can a group analysis recover deliberately injected focal signal? | A synthetic cohort with known injections, permutation testing, and specified masks; results depend on injection design and ground-truth definition. |
| [Cross-site/sequence profiles](cross_sequence_benchmark.md) | Do regional metabolic patterns replicate across independent acquisitions? | Three real-data cohort comparisons; evaluates relative regional pattern, not agreement of absolute concentrations. |

The public [SynthMRSI-Project demo](usage_basic.md) is an onboarding and
end-to-end test fixture. The VBA page describes a separately identified
injection dataset; use the dataset and version named by each benchmark.

## Interpret the comparisons

Leakage measures signal outside a reference mask. Detection assesses
recovery of a particular planted abnormality. Profile replication measures
agreement of regional patterns. A configuration's rank on one measure need
not predict its rank on another. The two ANTs variants labelled similarly
in the registration and VBA pages also have different MRSI→T1w transform
chains; each page specifies them explicitly.

The small registration/runtime sample does not establish a universal
backend ranking. Cross-cohort regional correlation does not establish
scanner-independent absolute quantification, subject-level interchangeability,
or agreement in disease effects. These results complement the recording-level
[QC review](outputs.md) required for a new study.

## Reproduce and extend a benchmark

Use the dataset/version, hardware, configuration, exclusions, and metrics
listed on the corresponding page. For new runs, retain:

- MRSIPrep version, source commit, and immutable container image digest.
- Exact command or preset plus the resolved provenance JSON.
- Dataset version, selected recordings, acquisition metadata, and QC exclusions.
- Output grids, quality masks, atlas versions, and downstream statistical settings.
- Runtime metrics and cache policy; distinguish registration-only timings
  from full-pipeline timings.
- Random seeds where the relevant tool exposes them, or the resulting
  stochastic outputs when an exact repeat cannot be guaranteed.

The existing pages do not constitute a complete executable reproduction
bundle: for example, the runtime report names the mutable `cpu` image tag,
and some experiment scripts referenced by the VBA page are local-only.
Do not infer a historical image digest or seed from the current release.
The [processing methods](methods.md) page describes the current algorithm
and reproducibility limits; commands below the individual benchmarks can
be used to collect new results with recorded settings.

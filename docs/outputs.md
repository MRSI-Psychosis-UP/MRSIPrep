# Outputs and quality control

After the [first run](usage_basic.md), inspect each recording before using
its derivatives in an analysis. Reports and provenance are written under:

```text
<output_dir>/mrsiprep/sub-01/ses-01/reports/
  sub-01_ses-01_desc-report.html
  sub-01_ses-01_desc-provenance.json
  sub-01_ses-01_desc-runtimemetrics.json
  figures/
```

For sessionless data, omit the session directory and filename entity.
Keep the report with its sibling assets when copying it to another location.

## Read the report

Use the [example report](examples/sub-01_ses-01/sub-01_ses-01_desc-report.md)
to see the panels without running the pipeline. This archived example uses
Chimera; available panels depend on the configuration and software version.

| Check | What to inspect | Reason to investigate |
|---|---|---|
| Raw MRSI and ventricle QC | Signal distribution, missing coverage, unusual bright clusters, and ventricular position | Acquisition artifacts or an orientation error can remain visible even when processing completes. |
| Tissue segmentation | GM/WM/CSF maps and anatomical labels | Gross tissue misclassification changes PVC and regional weighting. |
| Spike filtering | Before/after slices, repaired-voxel counts, and histograms | Extensive repairs or loss of a coherent signal feature warrant reviewing the inputs and filtering settings. |
| T1 correction and PVC | Before/after maps and correction summaries, when enabled | Large changes, clipped values, or an unexpected correction mode need explanation. |
| Registration | Reference-metabolite overlays in T1w and MNI space | Check internal structures as well as the outer brain boundary. A low leakage value alone cannot establish correct internal alignment. |
| Coverage and CRLB | Per-parcel coverage and quality summaries | Parcels with little usable data can bias a regional analysis; use an explicit study-level inclusion rule. |
| Profiles/connectivity | Parcel identities and matrix structure when requested | Unexpected missing parcels or nearly constant profiles can reflect limited coverage or signal variation. |
| Runtime and provenance | Resolved settings, versions, and processing trace | Confirm the intended settings, input selection, and enabled stages. |

### Interpreting leakage and quality summaries

`confounds/*_desc-leakageqc.tsv` reports the fraction and percentage of
resampled **signal magnitude** outside the reference brain mask, separately
by space and metabolite. It uses the resampled CRLB threshold when a CRLB
map exists. It is a signal-mass measure, not a percentage of bad voxels or
a universal pass/fail criterion. Comparisons depend on the target mask,
resolution, and available quality maps.

Voxelwise quality masks and regional coverage answer different questions.
A native `qcmask` records finite, in-mask signal passing the available
SNR/linewidth/CRLB thresholds. Regional-table `coverage` is the proportion
of a parcel's native-grid voxels retained for a particular metabolite.
Check the [derivative definitions](data_reference.md) before combining
these measures across recordings.

## Find the derivatives

All paths below are relative to `<output_dir>/mrsiprep/sub-*/[ses-*/]`.

| Directory | Contents | Availability |
|---|---|---|
| `mrsi/orig/` | Native-grid signal copies, filtered maps, and registration reference | Ordinary runs |
| `mrsi/orig-t1corr/` | T1-saturation-corrected native-grid maps | T1 correction enabled |
| `mrsi/orig-pvc/` | PVC-corrected native-grid maps | PVC enabled |
| `mrsi/t1w/` | Final signal resampled onto the T1w reference | `--output-mrsi-t1w` or T1w output requested |
| `mrsi/mni/` | Final signal resampled into MNI152NLin2009cAsym | MNI output requested; default |
| `anat/synthseg/` | SynthSeg outputs, projected parcellations, and regional tables | Depends on the processing stage and backend |
| `confounds/` | Quality maps/masks, tissue probabilities, leakage, and correction summaries | Depends on available inputs and enabled stages |
| `mrsi/parcel/` | Regional-summary profile archives for legacy consumers | One per parcellation |
| `connectivity/` | Monte Carlo metabolic-profile archives; optional matrices, nodes, and edges | Profiles always; matrices with `--write-connectivity` |
| `transforms/` | Forward and inverse registration files | Depends on requested spaces and backend |
| `reports/` and `logs/` | HTML QC, figures, provenance, runtime metrics, and recording logbook | Ordinary runs |

Run-level logs live in `<output_dir>/mrsiprep/logs/`. Raw Chimera atlas
outputs live in `<output_dir>/chimera-atlases/`. The Nipype cache and
scratch data live in `--work-dir` (default `<output_dir>/work`). See
[Caching and reruns](running.md#caching-and-reruns) before removing that cache.

## Choose data for an analysis

For a voxelwise MNI analysis, use the final `mrsi/mni/*_desc-signal_mrsi.nii.gz`
maps from consistently configured runs. Their `desc-signal` name does not
encode every upstream correction: inspect the resolved configuration to
establish whether filtering, T1 correction, and PVC were enabled.

For regional analyses, choose the regional TSV or the summary archive in
`mrsi/parcel/`. The Monte Carlo archive in `connectivity/` contains
standardized, uncertainty-augmented features with a different shape and
masking procedure. These representations are not interchangeable; see
[Derivative formats](data_reference.md) for keys, dimensions, and missing-data
conventions, and [Processing methods](methods.md) for the statistical steps.

Retain the provenance JSON, command, container image identifier, acquisition
metadata, and your QC inclusion decisions with an analysis. Automated
indicators complement visual review and study-specific quality criteria.
For failed runs, see [Troubleshooting](troubleshooting.md); for report
regeneration, see [Batch runs, caching, and logs](running.md).

```{toctree}
:maxdepth: 1
:hidden:

Example report <examples/sub-01_ses-01/sub-01_ses-01_desc-report>
```

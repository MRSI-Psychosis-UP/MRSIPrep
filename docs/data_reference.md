# Derivative formats

Use [Outputs and QC](outputs.md) to locate and review results. This page
defines the principal file formats used by downstream analyses. Input
filenames and acquisition metadata are specified in [Preparing inputs](inputs.md).

## Image naming and values

Names carry subject/session, space, metabolite, and description entities.
For example:

```text
sub-01_ses-01_space-mrsi_met-CrPCr_desc-signalspikefilt_mrsi.nii.gz
sub-01_ses-01_space-MNI152NLin2009cAsym_res-5_met-CrPCr_desc-signal_mrsi.nii.gz
sub-01_ses-01_space-mrsi_met-CrPCr_desc-qcmask_mask.nii.gz
```

The output native space is named `mrsi`; the primary input convention uses
`orig`. Use the NIfTI affine and dimensions to establish each file's grid.
The `res-` entity is a target voxel spacing in millimetres, not an estimate
of the acquisition's effective spatial resolution.

| Description/suffix | Meaning |
|---|---|
| `desc-signal` in `mrsi/orig/` | Copied native signal; orientation can be corrected in the derivative copy when requested |
| `desc-signalspikefilt` | Native signal after spike/missing-voxel repair |
| `desc-signalt1corr` / `desc-signalt1corrvoxelwise` | Native signal after the selected T1 correction |
| `desc-signalpvc` | Native signal after PETPVC and pipeline clipping |
| `desc-signal` in `mrsi/mni/` or `mrsi/t1w/` | Final downstream signal after enabled upstream corrections and resampling |
| `desc-qcmask`, suffix `mask` | Per-metabolite inclusion mask: `1` retained, `0` excluded |
| `desc-spikemask` | Voxels detected for spike repair; this is not a general quality mask |
| `label-GM`, `label-WM`, `label-CSF`, suffix `probseg` | Tissue class fractions/probabilities |
| `desc-crlb`, `desc-snr`, `desc-fwhm` | Quality values carried through from inputs; input units are retained |

Signal images are not guaranteed to be masked by every quality criterion.
Zeros can represent background, clipping, or a measured/repaired value;
they do not by themselves identify valid observations. Use the appropriate
quality and coverage information for your analysis. Quality masks are
native-space products; resampling quality maps does not create a new
combined quality mask in the output space.

## Regional metabolite TSV

`anat/synthseg/*_desc-regional_metabolites.tsv` contains one row per
represented parcel and requested metabolite. Atlas and scale entities
identify the parcellation.

| Columns | Definition |
|---|---|
| `subject`, `session`, `atlas`, `scale`, `parcel_id`, `parcel_name`, `hemisphere`, `metabolite` | Recording, parcel, and metabolite identifiers |
| `mean`, `median`, `std` | Summary of finite signal values within the parcel's metabolite-specific quality mask |
| `weighted_mean` | SNR-weighted mean over the same retained voxels; uniform weights if SNR is absent |
| `n_voxels` | Number of retained native-grid voxels for this parcel/metabolite |
| `coverage` | Retained voxel count divided by total parcel voxel count on the MRSI grid; range 0–1 |
| `mean_snr`, `mean_linewidth`, `mean_crlb` | Mean quality measures over retained voxels |
| `mean_gm_fraction`, `mean_wm_fraction`, `mean_csf_fraction` | Mean tissue fractions over retained voxels, when available |

Undefined summaries are written as empty TSV fields and generally load as
NaN. Parcels absent from the MRSI-grid atlas have no rows; represented
parcels with no passing voxels have `n_voxels=0` and undefined signal
summaries. Join recordings by identifiers, not by row position.

## Regional-summary archive: `mrsi/parcel/`

`*_desc-GMmetprofiles_mrsi.npz` (PVC enabled) or
`*_desc-metprofiles_mrsi.npz` (PVC disabled) exports the regional table in
an array layout used by legacy consumers. Let `P` be retained parcels and
`M` requested metabolites.

| Key | Shape / meaning |
|---|---|
| `metab_profiles` | `(P, M)`, selected `--regional-summary` statistic in upstream signal units after corrections |
| `parcel_labels`, `parcel_names`, `parcel_voxel_counts` | `(P,)`, parcel IDs, names, and total atlas voxel counts; counts are not per-metabolite passing counts |
| `metabolites` | `(M,)`, column order |
| `water_signal` | `(P,)`, mean water signal when supplied, otherwise NaN |
| `parcel_label_ids_ignore`, `parcel_labels_ignore` | IDs and names of parcels omitted from the retained arrays |
| `metadata`, `preproc_option`, `profile_source`, image paths and recording/atlas fields | Processing and source metadata |

A parcel is retained if it has native-grid atlas voxels and at least one
finite metabolite summary. Other metabolite entries can still be NaN.
Some label and metadata arrays use Python objects; accessing those arrays
with NumPy requires `allow_pickle=True`, which should only be used for
archives from a trusted source.

## Monte Carlo profile archive: `connectivity/`

`*_desc-metabolicprofiles_mrsi.npz` is written independently of
`--write-connectivity`. Let `P` be selected parcels, `M` metabolites, and
`K` the stored `npert` value.

| Key | Shape / meaning |
|---|---|
| `features` | `(P, M*K)`, z-scored, parcellated perturbations; metabolite-major order with the `K` draws contiguous for each metabolite |
| `parcel_concentrations` | `(M, P)`, unstandardized parcel means from the corrected signal maps |
| `labels_indices`, `parcel_names` | `(P,)`, row IDs and names |
| `metabolites` | `(M,)`, metabolite order |
| `npert`, `sigma_scale`, `gm_weighted` | Scalar sampling and weighting settings |

For example, in a Python analysis environment:

```python
import numpy as np

with np.load("path/to/recording_desc-metabolicprofiles_mrsi.npz") as archive:
    features = archive["features"]
    n_metabolites = len(archive["metabolites"])
    n_draws = int(archive["npert"])
    profiles = features.reshape(features.shape[0], n_metabolites, n_draws)
    parcel_ids = archive["labels_indices"]
```

Use the actual archive filename from your output directory; it also carries
atlas, perturbation-count, and processing tokens. `features` are standardized
features, while `parcel_concentrations` retain the signal scale. This profile
path uses the brain mask and optional GM weighting, rather than the regional
TSV's per-metabolite quality-mask reduction. Parcel exclusion options affect
this representation. With no CRLB maps, `npert` is reduced to `1`; missing
CRLB for an individual metabolite contributes zero injected noise.

## Optional connectivity files

With `--write-connectivity`, `*_desc-connectivity_mrsi.npz` stores a
`matrix` of shape `(P, P)` plus `labels_indices`, `parcel_names`,
`metabolites`, `parcel_concentrations`, `method`, `npert`, `sigma_scale`,
and `gm_weighted`. The accompanying matrix TSV uses parcel names as row
and column labels. Node and edge TSVs provide tabular exports of the same
parcellation and pairwise values.

These are metabolic-profile similarities, or distances when
`euclidean_distance` is selected. Interpret them according to `method`;
they are not axonal connections or temporal correlations.

## QC tables and provenance

`confounds/*_desc-mrsiqc.tsv` summarizes quality measures by metabolite.
`*_desc-leakageqc.tsv` contains `space`, `metabolite`, `n_quality_voxels`,
`total_signal_mass`, `leakage_signal_mass`, `leakage_fraction`, and
`leakage_percent`; leakage is undefined when total signal mass is zero.
T1 correction tables are specified in [Experimental features](future_development.md).

`reports/*_desc-provenance.json` records resolved configuration, software
versions, output paths, and a configuration-derived `pipeline_trace` of
enabled/skipped stages. That trace describes configured stage gating;
consult logs and runtime metrics for execution and cache history.

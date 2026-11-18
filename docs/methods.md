# Processing methods

This page explains what happens to quantified maps and which assumptions
affect their interpretation. For runnable commands, use the
[user guide](configuration.md); for software extension points, use
[Architecture](architecture.md). Record the resolved configuration with
an analysis, since many stages are conditional.

## Processing order

Each recording follows a cached sequence. Related stages are grouped here
in their execution order:

| Order | Stages | Main operations |
|---|---|---|
| 1 | Input preparation, tissue segmentation, anatomical preparation | Validate inputs, select the T1w reference, compute or reuse GM/WM/CSF maps, and prepare the anatomical registration target. |
| 2 | MRSI preprocessing | Copy source maps; optionally correct orientation; establish the brain mask; repair spikes/missing voxels; optionally apply T1 saturation correction; build the registration reference and quality masks. |
| 3 | Registration, tissue probability resampling, tissue QC | Fit MRSI→T1w and, when needed, T1w→MNI transforms; bring tissue probabilities onto the native MRSI grid. |
| 4 | PVC, output resampling, leakage QC | Correct native-grid maps when enabled; compose transforms for final output maps; measure signal outside reference brain masks. |
| 5 | SynthSeg parcel QC, selected parcellation, regional extraction | Project labels to the MRSI grid, measure coverage/quality, and summarize metabolite values by region. |
| 6 | Metabolic profiles, optional connectivity, legacy profile export, reports | Propagate CRLB-scaled uncertainty, optionally correlate parcel features, export regional summaries, and assemble reports/provenance. |

In longitudinal mode, tissue and anatomical preparation run in a subject-level
pre-pass so the shared template can be built before individual sessions are
processed. See [Longitudinal processing](usage_longitudinal.md).

## Masking and quality criteria

The native MRSI inclusion mask comes from a supplied brain mask, otherwise
positive water signal, otherwise the union of finite positive metabolite
signal. This fallback represents signal support; it is not a new anatomical
brain segmentation.

For each metabolite, the quality mask combines finite signal, the native
inclusion mask, and all available quality-map thresholds. Proton defaults
are SNR ≥ 4, linewidth ≤ 0.1, and CRLB ≤ 20%. Maps are compared numerically
without unit conversion; confirm [input units](inputs.md#maps-units-and-geometry)
and definitions for the acquisition. `--quality-metrics` determines which
maps must exist, rather than which present maps are thresholded.

## Spike repair and T1 saturation correction

Spike detection starts from an intensity percentile (default 99th).
Connected-component size protects coherent large clusters; an extreme
cluster-intensity rule can still bring a large cluster back into repair.
The default size cap derives from native voxel size and the extreme
cluster z-score threshold defaults to 4. Review these choices when studying
focal metabolic abnormalities.

Repair uses local median replacement and biharmonic inpainting, followed
by Gaussian smoothing applied to repaired/missing voxels. The default
smoothing FWHM is the mean native voxel dimension times √2, rounded to
millimetres. It is not an additional whole-volume smoothing step.
See [Filtering settings](processing.md#spike-filtering).

Optional T1 saturation correction is applied after filtering and before
the registration reference and downstream PVC. Literature mode uses one
factor per metabolite/recording; voxelwise mode uses measured flip angle.
Both use literature metabolite T1 values and acquisition metadata. Neither
performs spectral fitting or a complete absolute-concentration calibration.
[Experimental features](future_development.md) specifies validation limits.

## Tissue processing and partial-volume correction

The default backend uses SynthSeg for brain extraction/anatomical labels
and FSL FAST for GM/WM/CSF probabilities. Existing CAT12 probabilities can
be reused instead. Tissue probabilities are linearly resampled into MRSI
space with the inverse registration transform.

PETPVC's region-based voxelwise (RBV) correction consumes the GM/WM/CSF
stack and native metabolite maps. Its isotropic point-spread width defaults
to the mean MRSI voxel dimension. MRSIPrep then sets negative output,
values exceeding twice the input signal, and signal outside the native
brain mask to zero. Those zeros can reflect clipping, so inspect the PVC
panel and retain that processing choice with downstream results.

`--no-pvc` disables this correction. `--tissue-backend none` also disables
PVC and tissue-fraction weighting, while anatomical parcellation still
runs. [Tissue processing](processing.md) lists the available combinations.

## Registration and interpolation

Default ANTs MRSI→T1w uses rigid plus SyN (`sr`), while T1w→MNI uses rigid,
affine, and SyN (`s`). These are separate registrations with different
transform stages. FSL offers FLIRT, with optional FNIRT for MRSI→T1w;
its T1w→MNI stage is affine. See
[Registration and output spaces](usage_normalization.md) for controls.

Final MNI maps apply the composed transform chain directly from the
corrected native signal. Continuous signal and quality maps use linear
interpolation; categorical atlases and spike masks use label-preserving
interpolation. Resampling to a finer grid does not improve acquisition
resolution and can change apparent smoothness and regional boundaries.
Native-resolution-derived MNI spacing is the default.

## Regional summaries and metabolic profiles

The regional TSV summarizes corrected native signal within each parcel
using the metabolite-specific quality mask. It reports mean, median,
standard deviation, SNR-weighted mean, coverage, and quality/tissue measures.
The legacy `mrsi/parcel/` archive selects the configured regional statistic
from that table.

The Monte Carlo representation in `connectivity/` is a separate calculation.
For each draw and metabolite, Gaussian noise has standard deviation
`signal * CRLB / 100 * sigma_scale` (default scale 2). Noisy values are
clipped to zero and an intensity-derived upper bound, masked by the brain
mask, z-scored per metabolite over the volume, and averaged within parcels,
with GM-fraction weighting when available. It uses the brain mask rather
than the regional TSV's per-metabolite QC mask.

The resulting per-parcel vector contains all metabolite/draw combinations.
`--write-connectivity` compares those vectors with the configured method
(default Spearman). These are metabolic-profile relationships; they do not
measure anatomical connections or temporal coupling.

Missing CRLB is treated as zero injected noise for that metabolite. If all
CRLB maps are absent, one draw is stored. This preserves a point-estimate
representation but does not supply measured uncertainty. The current CLI
does not expose or archive a fixed Monte Carlo seed, so fresh recomputations
can differ numerically even with the same settings. Cached reruns reuse
existing results. [Derivative formats](data_reference.md) defines array order
and missing-data conventions.

## Validation and reporting

Visual reports, coverage measures, and leakage checks describe different
aspects of quality; none alone establishes suitability for a study.
Consult the [validation overview](validation.md) for the evidence supporting
runtime, registration, focal-signal detection, and cross-acquisition profiles.
Read [Limitations and scope](limitations.md), and cite the software and
relevant processing methods as described in [How to cite](citing.md).

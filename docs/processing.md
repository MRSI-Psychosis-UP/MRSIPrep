# Tissue processing, filtering, and PVC

Choose processing settings for your acquisition after checking the
[input requirements](inputs.md). For the algorithm order and assumptions,
see [Processing methods](methods.md).

## Tissue backends

| Backend | Tissue probabilities | Practical requirements |
|---|---|---|
| `synthseg-fast` (default) | SynthSeg brain extraction followed by FSL FAST | Raw T1w; both tools are bundled in the container |
| `existing` | Reuse CAT12 GM/WM/CSF maps | Raw T1w, skull-stripped T1w, and all three CAT12 probability maps; requirements below |
| `none` | Skip tissue probabilities and PVC | Anatomical parcellation still runs; use a compatible registration target |

`--synthseg-mode robust` is the default inference mode. `standard` and
`fast` trade inference robustness for runtime/memory. The tissue-backend
name `synthseg-fast` describes the SynthSeg-plus-FAST combination; it does
not imply `--synthseg-mode fast`.

`--tissue-backend existing` reuses precomputed CAT12 tissue maps; see
[Existing tissue derivatives](other_input_derivatives.md#existing-tissue-derivatives)
for its requirements and an example command.

Disable tissue segmentation and PVC entirely with `--tissue-backend none`
(equivalent to also passing `--no-pvc`):

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --tissue-backend none
```

If atlas/Chimera mode would otherwise select `brain-csf` and no CSF map
is available, also select `--registration-t1-target brain` or `raw` as
appropriate for the anatomical input. See [Registration targets](usage_normalization.md#anatomical-registration-target).

## Voxel-quality thresholds

For proton MRSI, defaults are `--snr-min 4`, `--linewidth-max 0.1`, and
`--crlb-max 20`. Adjust them to a documented acquisition-specific rule and
check the [input units](inputs.md#maps-units-and-geometry). A present quality
map is always applied to the native per-metabolite quality mask, even if
that metric is omitted from the list of required maps.

Selecting a quantification tool does not convert maps or thresholds.
For linewidth maps in the registry's Hz convention, set `--linewidth-max`
to your protocol's cutoff in Hz; the numeric default `0.1` is not converted.

Review the report's quality and coverage summaries before using those masks
for a cohort. [Processing methods](methods.md) explains how regional tables
and Monte Carlo profiles use different inclusion procedures.

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

`--spikepc` controls the candidate intensity percentile (default 99).
`--spike-max-cluster-voxels` controls the maximum connected-cluster size
repaired by the size rule; its default derives from native voxel size.
Larger clusters are normally preserved, but an extreme cluster mean can
still trigger repair (`--spike-extreme-zscore`, default 4). Compare the
before/after panels when a coherent abnormality is central to the analysis.

## Partial-volume correction

PETPVC RBV runs by default after tissue probabilities have been resampled
onto the MRSI grid. Use `--no-pvc` to retain the pre-PVC signal in downstream
outputs while still computing tissue probabilities. `--tissue-backend none`
disables both tissue processing and PVC.

The correction uses an isotropic point-spread width derived from the mean
native voxel size. MRSIPrep clips negative, out-of-mask, and large-overshoot
values in the result; see [Processing methods](methods.md#tissue-processing-and-partial-volume-correction)
and review the PVC report panel before interpreting signal changes.

## Optional saturation correction

T1 saturation correction is separate from PVC and is disabled by default.
The [experimental-features guide](future_development.md#t1-saturation-correction)
describes literature and measured-flip-angle modes, required metadata,
supported metabolites, and outputs.

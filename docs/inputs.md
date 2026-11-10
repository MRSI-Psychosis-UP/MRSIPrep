# Preparing inputs

Prepare two inputs: **quantified NIfTI maps** and a required
**`mrsinmrs.json` dictionary** describing acquisition and quantification.
Export the maps from your fitting software before arranging them below.

## NIfTI and MRSinMRS inputs

### Required files and layout

For each subject/session, provide:

| Input | Requirement |
|---|---|
| T1w anatomical | One anatomical image for the recording. |
| Metabolite signal/concentration | One map per requested metabolite. |
| CRLB | One map per requested metabolite, required by default. |
| SNR | One shared map, required by default. |
| Linewidth/FWHM | One shared map, required by default. |
| `mrsinmrs.json` | Required by default; see [Acquisition metadata](#acquisition-metadata-mrsinmrsjson). |

This example contains one metabolite. Repeat the signal/CRLB pair for each
additional metabolite:

```text
bids/
├── dataset_description.json
├── sub-01/
│   └── ses-01/
│       └── anat/
│           └── sub-01_ses-01_T1w.nii.gz
└── derivatives/
    └── mrsi-orig/
        ├── mrsinmrs.json
        └── sub-01/
            └── ses-01/
                ├── sub-01_ses-01_space-orig_met-CrPCr_desc-signal_mrsi.nii.gz
                ├── sub-01_ses-01_space-orig_met-CrPCr_desc-crlb_mrsi.nii.gz
                ├── sub-01_ses-01_space-orig_desc-snr_mrsi.nii.gz
                └── sub-01_ses-01_space-orig_desc-fwhm_mrsi.nii.gz
```

Use matching subject/session labels throughout. For datasets without
sessions, omit `ses-01/` and `_ses-01` everywhere. Both `.nii` and
`.nii.gz` are accepted.

| Entity/suffix | Meaning |
|---|---|
| `space-orig` | Native MRSI acquisition grid (prior to any MRSIPrep registration). |
| `met-<name>` | Fitted metabolite/group (e.g. `CrPCr`, `GluGln`); omitted on maps shared across all metabolites. |
| `desc-signal` | Quantified signal/concentration map for that metabolite. |
| `desc-crlb` | CRLB map for that metabolite. |
| `desc-snr` | Shared SNR map, no `met-` entity. |
| `desc-fwhm` / `desc-linewidth` | Shared linewidth map, no `met-` entity; either name is accepted. |
| `desc-brainmask` | Optional shared inclusion mask. |
| `met-water_desc-signal` | Optional water-signal map. |
| `desc-b1map` | Optional measured flip-angle map (degrees); required only for voxelwise T1 correction. |
| `mrsi` | Fixed modality suffix for all MRSI maps. |

Additional anatomical inputs for reusing tissue segmentation are
described in [Tissue backends](processing.md#tissue-backends).

### Maps, units, and geometry

All MRSI signal and auxiliary maps must share spatial dimensions, voxel
sizes, and NIfTI affines. Supply individual 3D scalar maps. The T1w has its
own anatomical grid; MRSIPrep registers the MRSI to it.

Preserve the upstream signal/concentration units. CRLB must be a
**percentage** (`20` means 20%, not `0.20`). SNR definitions and linewidth
units must match the [quantification convention](mrsinmrs.md#quantification-tool-conventions)
declared in the metadata.

### Required quality maps versus inclusion thresholds

By default, `--quality-metrics snr linewidth crlb` requires all three
quality metrics. If your fitter only supplies CRLB, use
`--quality-metrics crlb`; SNR and linewidth may then be absent.
Every quality map that is present is still thresholded, even if omitted
from this list. Numerical cutoffs belong in
[Processing settings](processing.md#voxel-quality-thresholds).

## Acquisition metadata: `mrsinmrs.json`

Place the dictionary at **`<bids_dir>/derivatives/mrsi-orig/mrsinmrs.json`**,
at the root of the MRSI inputs. This is a MRSIPrep convention, not a
standard BIDS sidecar. To use another location, pass
`--mrsinmrs-file /path/to/metadata.json` (a host path with
`mrsiprep-docker`). A missing, invalid, or empty file stops the run.

See [MRSinMRS](mrsinmrs.md) for the full dictionary structure, required
fields, and unit conventions.

Once both inputs are prepared, continue to [First run](usage_basic.md)
for validation and processing commands.

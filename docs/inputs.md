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
units must match the [quantification convention](#quantification-tool-conventions)
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

### Minimum information and dictionary fields

Only `CommonMetadata` (an object) and `Recordings` (an optional list of
objects) are accepted at the top level. Put shared fields in
`CommonMetadata` and subject/session differences in `Recordings`:

```json
{
  "CommonMetadata": {
    "QuantificationTool": "lcmodel",
    "LinewidthUnit": "Hz",
    "CRLBUnit": "percent",
    "Nucleus": "1H",
    "SequenceName": "YOUR_SEQUENCE_NAME",
    "RepetitionTime": 0.457,
    "EchoTime": 0.03,
    "FlipAngle": 45,
    "MagneticFieldStrength": 3
  },
  "Recordings": [
    {"sub": "01", "ses": "01", "RepetitionTime": 0.45},
    {"sub": "02", "ses": "01", "RepetitionTime": 0.46, "FlipAngle": 42}
  ]
}
```

Replace example acquisition values with your protocol. A matching recording
overrides common fields for that subject/session only — here, `sub-02`
uses its own `RepetitionTime` and `FlipAngle` while still inheriting
`Nucleus`, `SequenceName`, `EchoTime`, and `MagneticFieldStrength` from
`CommonMetadata`. An entry without `ses` applies when no exact session
entry matches. `QuantificationTool`, `LinewidthUnit`, `CRLBUnit`, and
`Nucleus` are run-wide settings read from `CommonMetadata` or the CLI, not
recording overrides.

`QuantificationTool`, `LinewidthUnit`, and `CRLBUnit` are each
**mandatory**, either here or via `--quantification-tool`,
`--linewidth-unit`, `--crlb-unit` respectively (a CLI flag overrides the
dictionary; the metadata file is still required even then).
`RepetitionTime`, `FlipAngle`, and `MagneticFieldStrength` become
mandatory when T1 correction is enabled, and `MagneticFieldStrength` is
also mandatory whenever `LinewidthUnit` is `ppm` (needed to convert to
Hz). `Nucleus` defaults to `1H` (`--nucleus` overrides it). `SequenceName`,
`EchoTime`, and other acquisition details are optional and included in
the QC report for reference, but have no effect on processing.

### Quantification tool conventions

This declaration tells MRSIPrep how to interpret quality values before
thresholding:

| Value | Applicable output |
|---|---|
| `lcmodel` | LCModel-derived quality maps. |
| `fsl-mrs` | FSL-MRS-derived quality maps. |
| `osprey` | Osprey's **LCModel-wrapper** output. |
| `custom` | Other exports converted upstream to the expected convention. |

The current registry expects CRLB in **percent**, SNR as **peak height over
residual-noise SD**, and linewidth in **Hz**. All current handlers leave
values unchanged: selecting a tool does not convert units or change
thresholds. Check your export convention, including for listed tools.
Use `custom` for unlisted workflows or Osprey's native fitter after
preparing compatible maps; MRSIPrep supplies no conversion for them.

### Linewidth and CRLB units

`LinewidthUnit` and `CRLBUnit` declare the unit the upstream tool's maps are
*actually stored in* — independent of, and in addition to, the
`QuantificationTool` convention above. `--linewidth-max`/`--crlb-max`
thresholds are always applied in Hz/percent, so both declarations are
**mandatory**, with no default: an unconverted ppm linewidth thresholded as
if it were Hz (or vice versa) would silently pass or fail the wrong voxels.

| Field | Accepted values | Notes |
|---|---|---|
| `LinewidthUnit` | `Hz`, `ppm` | `ppm` is converted to Hz using `MagneticFieldStrength` (mandatory in `CommonMetadata` when `LinewidthUnit` is `ppm`) and the declared nucleus's Larmor frequency. Conversion is currently curated for `1H` only. |
| `CRLBUnit` | `percent` | Declared explicitly rather than assumed; only `percent` is supported today. |

`SNRUnit` is optional and not currently used for conversion — SNR is
treated as unitless regardless of what, if anything, is declared.

Acquisition reporting follows [Lin et al. (2021), *Minimum Reporting
Standards for in vivo Magnetic Resonance Spectroscopy (MRSinMRS): Experts'
consensus recommendations*](https://doi.org/10.1002/nbm.4484).
The JSON layout above is a MRSIPrep convention, not a standard sidecar.

Once both inputs are prepared, continue to [First run](usage_basic.md)
for validation and processing commands.

# MRSinMRS

Acquisition reporting follows [Lin et al. (2021), *Minimum Reporting
Standards for in vivo Magnetic Resonance Spectroscopy (MRSinMRS): Experts'
consensus recommendations*](https://doi.org/10.1002/nbm.4484). The
`mrsinmrs.json` layout described here is a MRSIPrep convention built around
that standard, not a standard sidecar format itself. See
[Preparing inputs](inputs.md#acquisition-metadata-mrsinmrsjson) for where to
place the file and the basic requirement.

## Minimum information and dictionary fields

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

## Quantification tool conventions

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

## Linewidth and CRLB units

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

Once both inputs are prepared, continue to [First run](usage_basic.md)
for validation and processing commands.

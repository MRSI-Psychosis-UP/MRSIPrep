# Preparing inputs

MRSIPrep consumes quantified NIfTI metabolite maps and a T1w anatomical
image. Export maps from your reconstruction/quantification software before
arranging them in the layout below. The MRSI input convention is specific
to MRSIPrep; the `derivatives/mrsi-orig/` directory contains the maps to be
processed, even though it is named `derivatives`.

## Required directory layout

This complete two-metabolite example uses the default quality-map
requirements. Repeat the signal and CRLB pair for every requested metabolite.

```text
bids/
  dataset_description.json
  sub-01/
    ses-01/
      anat/
        sub-01_ses-01_T1w.nii.gz
  derivatives/
    mrsi-orig/
      mrsinmrs.json                     required acquisition metadata
      sub-01/
        ses-01/
          sub-01_ses-01_space-orig_met-CrPCr_desc-signal_mrsi.nii.gz
          sub-01_ses-01_space-orig_met-CrPCr_desc-crlb_mrsi.nii.gz
          sub-01_ses-01_space-orig_met-GluGln_desc-signal_mrsi.nii.gz
          sub-01_ses-01_space-orig_met-GluGln_desc-crlb_mrsi.nii.gz
          sub-01_ses-01_space-orig_desc-snr_mrsi.nii.gz
          sub-01_ses-01_space-orig_desc-fwhm_mrsi.nii.gz
```

For a dataset without sessions, omit every `ses-01/` directory and the
`_ses-01` filename entity, then omit `--session-label` in commands. Subject
and session labels must agree across anatomical and MRSI inputs.
Compressed `.nii.gz` and uncompressed `.nii` maps are accepted.

For compatibility with existing synthetic datasets, input discovery also
checks `derivatives/mrsiprep/sub-01/ses-01/mrsi/orig/` when the primary
`mrsi-orig` directory for that recording is absent or empty. Prefer the
primary layout for new datasets so source maps remain distinct from outputs.

## Maps, units, and geometry

| Input | Requirement | Interpretation |
|---|---|---|
| T1w anatomical | Required | A usable anatomical image for segmentation and registration; it has its own anatomical grid. |
| `met-<name>_desc-signal` | Required for each requested metabolite | Quantified signal or concentration in your upstream units; MRSIPrep does not infer an absolute concentration calibration. |
| `met-<name>_desc-crlb` | Required by default for each metabolite | Percentage uncertainty: `20` means 20%, not `0.20`. |
| `desc-snr` | Required by default; one shared map | SNR values as defined by your quantification method; default minimum is `4` for proton MRSI. |
| `desc-fwhm` or `desc-linewidth` | Required by default; one shared map | Numeric linewidth compared directly with `--linewidth-max` (default `0.1` for proton MRSI). Use ppm with that default, or convert the map/threshold consistently for an export in Hz. No unit conversion is performed. |
| `desc-brainmask` | Optional | Native-grid inclusion mask; nonzero values are included. |
| `met-water_desc-signal` | Optional | Native-grid water signal; positive voxels define the fallback mask when no mask is supplied. |
| `desc-b1map` | Required only for voxelwise T1 correction | Measured flip angle in degrees on the metabolite grid; a relative B1 scaling map must first be converted to flip angle. |

All MRSI maps and their masks must refer to the same spatial grid and
orientation: matching dimensions, voxel sizes, and NIfTI affine. Scalar
maps must be 3D after singleton dimensions are removed. Preflight checks
metabolite grids, but it does not replace checking the geometry of every
auxiliary map. Do not reshape arrays to make them match; resample with the
correct physical geometry upstream.

If your exporter supplies SNR or linewidth separately for each metabolite,
the current loader still expects the shared, non-`met-` filenames above.
Choose and document the shared quality measure appropriate to the acquisition.

### Required quality maps versus inclusion thresholds

`--quality-metrics` controls which missing quality maps cause validation
to fail. The default is `snr linewidth crlb`. If your quantification method
only provides CRLB, use:

```bash
  --quality-metrics crlb
```

Every available SNR, linewidth, and CRLB map is still used to form the
quality masks, even if it is not listed in `--quality-metrics`. Thresholds
are configured separately with `--snr-min`, `--linewidth-max`, and
`--crlb-max`; see [Processing settings](processing.md).

## Metabolite names and T1w selection

Pass metabolite names as a comma-separated list, and include the reference
metabolite in that list:

```bash
  --metabolites CrPCr,GluGln --ref-met CrPCr
```

Input discovery tries exact names first, then nucleus-specific aliases.
Common proton aliases include `tCr`/`CrPCr`, `Glx`/`GluGln`, and
`Cho`/`GPCPCh`. Alias lookup finds files; it does not combine separately
quantified metabolites or change their scientific meaning. Use names
consistent with the actual fitted resonance groups. Experimental T1
correction requires exact literature-table names, as described in
[Experimental features](future_development.md).

When multiple raw T1w candidates are present, selection prefers
`acq-memprage`, `acq-mprage`, or `acq-mp2rage`, then `run-01`.
Use `--t1 acq-mprage_T1w` to select a filename substring, or use
`--bids-filter-file` with a JSON filter such as:

```json
{"t1w": {"acquisition": "mprage", "run": "01"}}
```

With the standard `/data` container mount, a filter saved at the BIDS root
as `t1w_filter.json` is passed as `--bids-filter-file /data/t1w_filter.json`.
The [CLI reference](cli_reference.md) describes supported filter entities.

## Acquisition metadata: `mrsinmrs.json`

MRSinMRS acquisition metadata is **required**. By default, place the file at
**`derivatives/mrsi-orig/mrsinmrs.json`**, at the
root of the MRSI input tree rather than the BIDS dataset root. It records
acquisition information following the MRSinMRS reporting recommendations:

Lin, A., Andronesi, O., Bogner, W., et al. (2021).
[Minimum Reporting Standards for in vivo Magnetic Resonance Spectroscopy
(MRSinMRS): Experts' consensus recommendations](https://doi.org/10.1002/nbm.4484).
*NMR in Biomedicine*, **34**(5), e4484.

The filename and JSON structure below are MRSIPrep conventions; the paper
defines reporting recommendations, not this JSON schema. For example:

```json
{
  "CommonMetadata": {
    "Nucleus": "1H",
    "RepetitionTime": 0.457,
    "FlipAngle": 45,
    "MagneticFieldStrength": 3,
    "SequenceName": "ECCENTRIC"
  },
  "Recordings": [
    {"sub": "01", "ses": "01", "RepetitionTime": 0.45}
  ]
}
```

These are example acquisition values; replace them with your protocol.

### Use a custom metadata file

To keep metadata elsewhere, specify its path explicitly:

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --metabolites CrPCr,GluGln --ref-met CrPCr \
  --mrsinmrs-file /path/to/acquisition_metadata.json
```

The wrapper accepts a **host path** and mounts this file read-only. The
Command builder exposes the same `--mrsinmrs-file` option. With plain
Docker, mount the file yourself and pass its path inside the container.

An explicit path overrides the default. If the selected file is missing,
unreadable, malformed, or contains no acquisition metadata, MRSIPrep exits
with a configuration error before processing. The same requirement applies
to `--validate-only` and `--reports-only`. A BIDS-root `mrsinmrs.json` is
not discovered automatically: move it into `mrsi-orig` or select it with
`--mrsinmrs-file`. Informational commands such as `--help`, `--hello-world`,
and `--list-presets` remain usable without a dataset.

### Metadata structure and units

Only `CommonMetadata` (an object) and `Recordings` (a list of objects) are
accepted at the top level. Supply nonempty acquisition information in at
least one of them; an empty JSON object is not a specification.
For each recording, common fields are overlaid by the matching subject and
session entry; a subject-only entry applies when no exact session entry
matches. Additional acquisition fields are included in the report.

TR is in **seconds**, flip angle in **degrees**, and field strength in
**Tesla**. These three values become mandatory when T1 correction is
enabled. `CommonMetadata.Nucleus` supplies the run-wide nucleus unless
`--nucleus` overrides it; per-recording nucleus overrides do not change
processing. See [Experimental features](future_development.md) for
non-proton acquisitions and the T1 metadata whitelist.

## Existing tissue derivatives and import helpers

The default `synthseg-fast` tissue backend computes segmentation itself.
With `--tissue-backend existing`, provide the skull-stripped T1w and all
three CAT12 probability maps:

```text
derivatives/skullstrip/sub-01/ses-01/sub-01_ses-01_desc-brain_T1w.nii.gz
derivatives/cat12/sub-01/ses-01/sub-01_ses-01_desc-p1_T1w.nii.gz
derivatives/cat12/sub-01/ses-01/sub-01_ses-01_desc-p2_T1w.nii.gz
derivatives/cat12/sub-01/ses-01/sub-01_ses-01_desc-p3_T1w.nii.gz
```

`p1`, `p2`, and `p3` represent GM, WM, and CSF. Keep these maps aligned with
the subject's anatomical image. [Tissue processing](processing.md) explains
backend choices and their interaction with registration targets.

Optional host-side helpers arrange already-NIfTI derivatives in the expected
layout:

```bash
pip install mrsiprep
mrsiprep-import /source/folder /path/to/bids --subject S001 --session V1
```

For the graphical importer, install `mrsiprep[gui]` and run
`mrsiprep-import-gui`. These helpers do not parse native LCModel, TARQUIN,
Osprey, or FSL-MRS output into NIfTI; that export remains an upstream step.

## Validate before processing

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label 01 --session-label 01 \
  --metabolites CrPCr,GluGln --ref-met CrPCr \
  --validate-only
```

Check the preflight inventory and resolve missing maps or geometry errors.
Then continue with [First run](usage_basic.md) or consult
[Troubleshooting](troubleshooting.md).

# First run

This tutorial processes one subject and opens its QC report. First complete
[Installation](installation.md), including the `--hello-world` check and
installation of the `mrsiprep-docker` wrapper (included in the recommended
[Command builder setup](installation.md#option-a-command-builder-recommended)). Allow at least 8 GB of
Docker-allocated RAM for this single-recording example.

## Download the demo dataset

The public **SynthMRSI-Project** dataset contains 32 subjects with real T1w
anatomicals, model-synthesized metabolite signal, and empirical CRLB/SNR/FWHM
maps. It is released under CC0:
[10.5281/zenodo.21477047](https://doi.org/10.5281/zenodo.21477047).

```bash
curl -L -o SynthMRSI-Project.zip \
  "https://zenodo.org/records/22014466/files/SynthMRSI-Project.zip"
unzip SynthMRSI-Project.zip -d SynthMRSI-Project
```

The archive has no enclosing directory, so keep `-d SynthMRSI-Project`.
The direct download URL identifies a specific dataset version; the concept
DOI above provides the available versions if that URL changes.

Acquisition metadata is required at
`SynthMRSI-Project/derivatives/mrsi-orig/mrsinmrs.json`. If an older archive
places it at `SynthMRSI-Project/mrsinmrs.json`, add
`--mrsinmrs-file SynthMRSI-Project/mrsinmrs.json` to both commands below,
or move the file into `derivatives/mrsi-orig/` first. See
[Acquisition metadata](inputs.md#acquisition-metadata-mrsinmrsjson).

## Validate one recording

```bash
mrsiprep-docker SynthMRSI-Project SynthMRSI-Project/derivatives participant \
  --participant-label 01 --session-label 01 \
  --t1 acq-mprage_T1w \
  --metabolites NAANAAG,GPCPCh,CrPCr,GluGln,Ins \
  --ref-met CrPCr \
  --validate-only
```

Review the preflight table for missing or unreadable inputs before running
the expensive stages. For your own dataset, follow [Preparing inputs](inputs.md)
and replace the paths, labels, metabolite names, and T1w selector.

## Process the recording

```bash
mrsiprep-docker SynthMRSI-Project SynthMRSI-Project/derivatives participant \
  --participant-label 01 --session-label 01 \
  --t1 acq-mprage_T1w \
  --metabolites NAANAAG,GPCPCh,CrPCr,GluGln,Ins \
  --ref-met CrPCr \
  --nthreads 8 --nproc 1 --verbose 2
```

The default run uses SynthSeg parcellation, SynthSeg plus FAST tissue
segmentation, spike filtering, PETPVC partial-volume correction, and ANTs
registration. It writes MNI-space maps, regional summaries, and metabolic
profiles. This configuration needs no FreeSurfer licence or `recon-all`.
Runtime depends on anatomical resolution and available resources; see
[Runtime benchmarks](benchmarks.md) for measured examples.

## Inspect the result

Open this file in a web browser:

```text
SynthMRSI-Project/derivatives/mrsiprep/sub-01/ses-01/reports/sub-01_ses-01_desc-report.html
```

On Linux, for example:

```bash
xdg-open SynthMRSI-Project/derivatives/mrsiprep/sub-01/ses-01/reports/sub-01_ses-01_desc-report.html
```

Check raw signal, spike repair, tissue segmentation, MRSI-to-T1w and MNI
alignment, and parcel coverage. A completed command does not by itself
establish that the recording is suitable for analysis. [Outputs and QC](outputs.md)
explains these checks and includes an example report.

## Continue with your data

For a prepared dataset, a minimal command is:

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr
```

Then choose [processing settings](configuration.md), a
[parcellation](usage_parcellation.md), or [output spaces](usage_normalization.md).
Use [Batch runs, caching, and logs](running.md) when expanding to a cohort.
For an interactive stage-by-stage explanation, see the
[walkthrough notebook](notebooks/README.md).

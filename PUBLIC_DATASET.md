# SynthMRSI-Project: a public test dataset for MRSIPrep

## What this is

A small, synthetic MRSI dataset for testing and validating the MRSIPrep
pipeline end-to-end. 32 subjects, single session each:

- **T1w anatomical images** — real, from two CC0 OpenNeuro datasets
  (ds000001, ds000117).
- **MRSI signal** — model-synthesized, conditioned on each subject's own
  T1w (5 metabolites: `NAANAAG`, `GPCPCh`, `CrPCr`, `GluGln`, `Ins`).
- **CRLB, SNR, FWHM** — real empirical acquisition-quality measures, copied
  directly from real MRSI acquisitions. Not synthetic.

This is **not real patient MRSI data**. It exists so that anyone can
download a small, realistic-shaped dataset and run the full MRSIPrep
pipeline against it without access to a real MRSI acquisition.

The raw MRSI data lives at:

```text
derivatives/mrsi-orig/sub-XX/ses-01/
```

This is MRSIPrep's own primary convention for raw MRSI input (there is no
ratified BIDS extension for MRSI yet, so MRSIPrep documents this
`derivatives/mrsi-<space>/` location as first-class raw data, the same
convention real acquisition datasets use) — treat it as raw data to
preprocess, not as a derivative someone else already computed for you.

## License

The dataset is released under **CC0** (see `dataset_description.json`),
inherited from its two CC0 OpenNeuro T1w sources. You are free to use,
modify, and redistribute it without restriction.

The **MRSIPrep code and Docker image** are separately licensed under a
CHUV academic non-commercial research license (see `LICENSE` in this
repository) — downloading this dataset grants no rights to that code.
The synthMRSI generation pipeline that created this dataset (model
training, inference, abnormality injection) is not published and is not
part of this release; the dataset is provided pre-generated only. There is
no regeneration support.

## Download

```bash
curl -L -o SynthMRSI-Project.zip "https://zenodo.org/records/21477048/files/SynthMRSI-Project.zip"
unzip SynthMRSI-Project.zip
```

This extracts a `SynthMRSI-Project/` directory in your current working directory (the zip's own top-level folder) -- don't pass `-d SynthMRSI-Project`, since that would double-nest it.

DOI: [10.5281/zenodo.21477047](https://doi.org/10.5281/zenodo.21477047)
(concept DOI — always resolves to the latest version; see the project's
`CITATION.cff` for the full citation.)

## Run MRSIPrep

```bash
docker pull mrsiup/mrsiprep:cpu

docker run --rm \
  -v "$(pwd)/SynthMRSI-Project:/data:ro" \
  -v "$(pwd)/SynthMRSI-Project/derivatives:/out" \
  -v /path/to/your/freesurfer/license.txt:/opt/freesurfer/license.txt:ro \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --session-label 01 \
  --mode mni-norm \
  --t1 acq-mprage_T1w \
  --metabolites NAANAAG,GPCPCh,CrPCr,GluGln,Ins \
  --ref-met CrPCr \
  --nthreads 8 --nproc 2 --verbose 2
```

You'll need a FreeSurfer license file (free, from
https://surfer.nmr.mgh.harvard.edu/registration.html) for `mri_synthseg`.

Preflight/file-integrity checks run automatically before any recording is
processed — a corrupt or missing input skips just that recording rather
than crashing the whole batch.

## Expected runtime

Roughly 1-2 minutes per subject with the default (ANTs) registration
backend on a modern multi-core machine; scale by `32 / --nproc` for the
full dataset. Use `--participant-label 01 02 03` to try a handful of
subjects first.

## Expected output

Per-subject outputs land under `derivatives/mrsiprep/sub-XX/ses-01/`:
metabolite maps in T1w/MNI space (`mrsi/`), tissue segmentation (`anat/`),
and QC reports (`reports/qc-reports/`). The QC HTML report is the fastest
way to check a run succeeded — open
`reports/qc-reports/sub-XX_ses-01_step-combined.html` in a browser.

## Ground truth (optional)

A separate archive, `SynthMRSI-Project-groundtruth.zip`, contains the
known abnormality-injection masks used to validate group-difference
detection (via `experiments/vba_randomise.py` and
`experiments/compare_ground_truth.py` in the MRSIPrep repository).

If you intend to run your own group-difference analysis and compare it
against the ground truth, **do not download the ground-truth archive
until after you've completed your own analysis** — looking at it first
defeats the blinding purpose of a validation dataset like this one.

# Troubleshooting

- Start with a full-detail run log at `<out>/mrsiprep/logs/mrsiprep_<timestamp>.log`,
  and the per-recording logbook at `sub-*/ses-*/logs/sub-*_ses-*_desc-mrsiprep_log.txt`
  for a single subject/session's history out of a larger batch (see
  "Verbosity, logging, and provenance" in [Basic Usage](usage_basic.md)).
- Re-run the same recording with `--verbose 2` (step-level detail) or
  `--verbose 3` (raw ANTs/`recon-all`/`mri_synthseg` subprocess output) to
  see exactly where a failure occurs.
- `--validate-only` checks all selected subject/session inputs before any
  expensive processing starts, run it first when troubleshooting a batch.
- `--check-external-libs` verifies required external binaries
  (ANTs/FSL/FreeSurfer/PETPVC/Chimera, as applicable to the selected mode)
  are present and exits.
- By default a batch run logs a recording's failure and continues with the
  rest; pass `--stop-on-first-crash` to abort immediately instead, which is
  often easier when debugging a single problematic recording.
- Report issues at
  [github.com/MRSI-Psychosis-UP/MRSIPrep/issues](https://github.com/MRSI-Psychosis-UP/MRSIPrep/issues).

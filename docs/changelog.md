# Changelog

## Unreleased

- **Breaking:** `--metabolites` and `--ref-met` are now required, with no
  defaults. `--b0` (and the field-strength-dependent default metabolite
  lists it selected between) has been removed entirely — there is no
  implicit metabolite list; always pass `--metabolites` explicitly as a
  comma-separated string, e.g. `--metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins`
  (previously space-separated). `--ref-met` (e.g. `CrPCr`) must likewise
  always be specified; it no longer defaults to `CrPCr`.
- Aligned the CLI more closely with fMRIPrep's conventions: added
  `--bids-filter-file` (JSON entity filters to force a specific T1w
  acquisition/run when a session has more than one candidate; only the
  `"t1w"` key is currently supported), a `-w` short alias for `--work-dir`,
  and `--stop-on-first-crash` (abort the whole run on the first recording
  failure instead of logging it and continuing). Renamed several `--help`
  argument-group titles to match fMRIPrep's section names where a reasonable
  analogue exists (e.g. "subject/session selection" →
  "Options for filtering BIDS queries"); groups with no fMRIPrep equivalent
  (quality thresholds, parcellation, connectivity, overwrite/recompute) keep
  their existing names. Cosmetic/additive only — no existing flag was
  renamed or removed.
- Added `--longitudinal` subject-template normalization (**experimental —
  not yet verified end-to-end on a full multi-session run**): for multi-session
  subjects, builds one unbiased ANTs template across sessions
  (`antsMultivariateTemplateConstruction2.sh`) and registers it to MNI once
  (`antsRegistrationSyN.sh -t s`), composing (session→template)+
  (template→MNI) for each session's final MNI-space maps instead of
  registering every session directly. This completes the previously dead
  `t1-template`/`template-mni` (`ses-all`) naming convention and preflight
  columns that had been stubbed but unimplemented, replacing the dead
  `--proc-mnilong` flag. No-op for single-session subjects. Requires
  `antsMultivariateTemplateConstruction2.sh`, `antsAI`,
  `AverageAffineTransform`, `AverageAffineTransformNoRigid`, `AverageImages`,
  `ImageMath`, `MultiplyImages`, `ImageSetStatistics`, and `MeasureMinMaxMean`
  on `$PATH`; added to the Docker CPU image's ANTs prune allowlist (the last
  two were only caught by a full real end-to-end `--longitudinal` run, which
  ran template construction to completion across all 4 iterations before
  failing at the final "MeasureMinMaxMean: command not found").
- Fixed broken ANTs CLI fallback: `antsRegistrationSyN.sh` calls `PrintHeader`
  internally for image header inspection, but the previous Docker pruning pass
  only kept the four binaries mrsiprep directly invokes and missed it —
  causing `PrintHeader: command not found` and registration failures during
  Chimera parcellation (confirmed by exhaustive grepping of all ANTs binary
  names against the script). Added `PrintHeader` to the kept set and updated
  the prune script with a comment documenting the complete verified dependency
  list.

## Unreleased (previous)

- Fixed Chimera parcellation: corrected the FreeSurfer subject-ID/output-path
  conventions, pinned `clabtoolkit==0.4.2` for compatibility with
  `chimera-brainparcellation>=0.3.1`, forced Chimera to run single-threaded
  (its own `--nthreads>1` path silently drops errors and unfinished work),
  and worked around Chimera's `--force` flag being a silent no-op upstream
  by deleting stale output ourselves when `--overwrite` is set.
- Added live progress milestones for Chimera's otherwise-silent 10-20+
  minute single-threaded run, shown at `--verbose 2` and above.
- Fixed `--overwrite` not being honored before reusing cached Chimera
  parcellation output.
- Added `--connectivity-exclude-parcels` and `--connectivity-max-parcel-id`
  to filter parcels out of the connectivity matrix by name substring or
  label ID.
- Widened and extended the `--validate-only` preflight table with CRLB/SNR/
  FWHM quality-map columns and a FreeSurfer reuse-status column; removed
  the unimplemented longitudinal-template columns.
- Refactored the participant workflow's per-subject orchestration into
  named step functions, consolidated subprocess-handling across ANTs/
  FreeSurfer/FSL/Chimera interfaces into a shared helper, and grouped the
  CLI's ~50 arguments into semantic `--help` sections (no behavior change).
- Trimmed the Docker image: pruned `/opt/ants` to only the binaries
  MRSIPrep actually calls (~2.6GB → ~100MB).
- Migrated documentation to Sphinx + Read the Docs theme with a
  Home/Installation/Usage split, and added a Publications section.

## 0.1.0

- Initial MRSIPrep package scaffold.
- Ported preprocessing, BIDS import, registration, tissue, parcellation, and connectivity foundations from MRSI-Metabolic-Connectome.

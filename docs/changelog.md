# Changelog

## 1.7.7

- Relabeled `docs/vba_benchmark.md`'s two ANTs configurations from
  "ANTs (SyN)" / "ANTs (no SyN)" to **ANTs (R+SyN)** / **ANTs (R+Aff)**
  throughout the page's prose, tables, and figures, for clarity and to
  avoid confusion with the differently-scoped genuine Rigid+Affine
  configuration on the Registration Frameworks benchmark page. Re-ran
  the CrPCr detection figures (`vba_detection_crpcr_4backend.png`,
  `vba_detection_crpcr_gm.png`) and the CrPCr/GluGln ROC/PR comparison
  (`vba_roc_pr_comparison.png`) from source, since matplotlib bakes
  labels into the rendered PNGs — a markdown-only text fix does not
  update already-generated figures. Two of the six affected figures'
  underlying `randomise` CrPCr results had been deleted by an earlier
  cleanup pass in this same benchmark's development; re-derived both
  (re-exported the CrPCr injection, re-filtered, re-resampled through
  all four backends' already-computed registration transforms, and
  re-ran `randomise`) rather than leaving them stale. Updated the
  CrPCr/GluGln ROC-AUC/PR-AUC table with the freshly re-derived numbers
  (small changes from permutation-test noise); the GM-precise
  Dice/ROC-AUC/boundary-distance table's re-derived numbers matched the
  previous release's exactly, so that table is unchanged. Also
  corrected a stale prose claim that FSL FLIRT+FNIRT's detected CrPCr
  cluster was merely "visibly smaller" than the other three backends —
  the re-rendered figure shows it detects zero significant voxels at
  that slice.

## 1.7.6

- Corrected the Registration Frameworks benchmark's fourth registration
  configuration (`docs/benchmarks.md`): the previous release's "ANTs (no
  SyN)" reused mrsiprep's default MRSI→T1w transform with SyN dropped,
  which is **Rigid-only** at that stage (mrsiprep's default
  `antsRegistrationSyN[sr]` never computes a separate Affine stage there
  to fall back to) — not a genuine Rigid+Affine configuration. This
  release replaces it with **ANTs (Rigid+Affine)**: a real second
  `antsRegistration transform="a"` run at the MRSI→T1w stage (new
  registration compute, 2 subjects × 2 targets), composed with the
  already-correct Rigid+Affine T1w→MNI transform (reused, no recompute
  needed there). Finding, now based on a genuine Rigid+Affine
  configuration: ANTs (Rigid+Affine) is the **second-leakiest** of all
  four configurations — 4.30% signal mass leakage at 3T and 4.73% at 7T,
  roughly 11-12× worse than the default ANTs (Rigid+SyN) pipeline, worse
  than FSL FLIRT-only at both field strengths, and at 7T even worse than
  FSL FLIRT+FNIRT. Adding a real affine correction at this stage
  increased leakage relative to rigid-only, a genuinely unexpected
  result flagged explicitly as untested territory for mrsiprep's own
  default configuration (which never uses affine at this stage without
  immediately following it with SyN), not a recommendation for using it.
  `docs/vba_benchmark.md`'s own, differently-scoped "ANTs (no SyN)"
  comparison (Rigid-only at MRSI→T1w, reusing existing transforms, no
  new registration compute) is unaffected by this change and now
  cross-references this page to avoid the two configurations being
  conflated.
- Added **ANTs (no SyN)** as a fourth registration configuration to the
  Registration Frameworks benchmark (`docs/benchmarks.md`), reusing the
  already-computed ANTs (SyN) run's linear-stage transforms with the
  deformable warp dropped — no registration recompute. Also corrected a
  pre-existing error in that page's transform-stage table and prose:
  mrsiprep's default MRSI→T1w ANTs transform (`antsRegistrationSyN[sr]`)
  is **Rigid + SyN with no separate Affine stage**, not "rigid+affine+SyN"
  as previously described; the T1w→MNI stage (`[s]`) is the one that
  genuinely runs the full Rigid+Affine+SyN pipeline. The same correction
  was applied to `docs/vba_benchmark.md`, where the fourth backend added
  in an earlier release was likewise mislabeled "ANTs (rigid+affine
  only)" — both pages now consistently use **ANTs (SyN)** / **ANTs (no
  SyN)**, with an explicit note on what "no SyN" means at each stage.
  Finding: unlike the VBA benchmark (where dropping SyN never clearly
  hurt, and sometimes helped, focal-signal detection), **the deformable
  SyN stage does real, measurable work for MNI-space leakage** — ANTs (no
  SyN) leaks roughly 10× more signal mass than full ANTs (SyN) at 3T
  (3.3% vs. 0.34%) and roughly 5× more at 7T (2.2% vs. 0.44%), even
  falling behind FSL FLIRT-only at 3T. ANTs (no SyN)'s registration-only
  runtime (not a full `mni-norm` run) is well under a minute at either
  field strength, reported with an explicit caveat that it isn't a
  like-for-like comparison to the other backends' full-pipeline
  runtimes.
- Extended the medial-vs-peripheral cortex follow-up
  (`docs/vba_benchmark.md`) with a third, independent CrPCr injection
  site: a bilateral deep white-matter sphere pair (~13mm radius,
  centrum semiovale, intersected with SynthSeg's own WM label so the
  injection never spills into gray matter or CSF — no finer WM
  sub-parcellation is available from this pipeline, so a size-matched
  sphere is the closest fair-volume analogue to the two cortical
  targets). All three regions (medial GM, peripheral GM, deep WM) are
  injected simultaneously in the same CrPCr channel and reported per
  region. Finding: **deep WM has the highest ROC-AUC of all three
  regions for every backend** (0.84-0.97, vs. Precuneus's 0.77-0.86 and
  Postcentral's 0.52-0.60), but its Dice (0.05-0.06) is far below
  Precuneus's (0.32-0.42) — strong group-level statistical separation
  without tight spatial precision, a materially different failure mode
  than Postcentral's near-total absence of signal. Also documents a
  pre-existing, unrelated ~700-voxel false-positive cluster (present
  before this follow-up existed, near posterior cingulate/periventricular
  CSF) that was inflating Hausdorff distance for every region; boundary
  distances are now restricted to detected voxels within 20mm of each
  region's own ground truth to avoid a single distant unrelated cluster
  dominating the metric (Dice/ROC-AUC/PR-AUC are unaffected and remain
  unrestricted).
- Added a **medial vs. peripheral cortex** follow-up to the Voxel-Based
  Detection Benchmark (`docs/vba_benchmark.md`), for CrPCr only. Injects
  a second, independent GM-only cluster — bilateral **postcentral gyrus**
  (primary somatosensory cortex, lateral convexity) — alongside the
  existing medial Precuneus injection, in the same CrPCr channel, using
  the same per-subject bump amplitude. Reports Dice/ROC-AUC/PR-AUC/
  boundary-distance separately per region across all four registration
  configurations. Finding: **no backend detects the peripheral cluster
  at `alpha=0.05`** (Dice 0.000 everywhere, ROC-AUC 0.52-0.60 — barely
  above chance), while the medial Precuneus injection is detected
  normally by every backend (Dice 0.32-0.43). Group-level statistics on
  the merged signal show a comparable mean group difference at both
  sites, but more than 2x higher inter-subject variability at the
  peripheral site (SD 138.3 vs. 62.5) — the direct, measurable signature
  of registration/inter-subject-alignment accuracy being worse for a
  superficial gyrus than a deeper medial structure, independent of which
  of the four registration configurations is used.
- Added a fourth registration configuration, **ANTs (rigid+affine
  only)**, throughout the Voxel-Based Detection Benchmark
  (`docs/vba_benchmark.md`) — both the original AAL-parcel comparison
  (CrPCr/Precuneus, GluGln/Thalamus) and the GM-precise boundary-tracking
  follow-up. It reuses the same MRSI→T1w/T1w→MNI registrations already
  computed for the full ANTs (rigid+affine+SyN) run — `antsRegistration`
  always writes the affine stage to its own independent transform file
  regardless of a later SyN stage, so the deformable warp can simply be
  dropped from the resampling chain with no registration recompute.
  Consistent finding across both metabolites and both ground-truth
  granularities: **ANTs affine-only matches or exceeds full ANTs SyN on
  every metric** (ROC-AUC, PR-AUC, Dice, boundary distance) — the
  deformable stage does not clearly improve focal, planted-signal VBA
  detection, and on the GM-precise Precuneus target affine-only is the
  best-performing backend overall (Dice 0.432 vs. SyN's 0.341, mean
  boundary distance 4.32mm vs. 5.47mm). Also fixes an unanchored-curve
  gap in the ROC/PR comparison figure (the plotted curves now reach the
  same endpoint anchors already used internally by the AUC calculation).
- Added a **GM-precise boundary-tracking follow-up** to the Voxel-Based
  Detection Benchmark (`docs/vba_benchmark.md`), for CrPCr/Precuneus
  only. The original CrPCr injection used the raw AAL Precuneus parcel,
  which is only ~62% gray matter in native T1w space and sweeps into
  adjacent white matter; this follow-up switches the injection's region
  *source* to `mri_synthseg --parc`'s own DKT cortical labels
  (`ctx-lh-precuneus`/`ctx-rh-precuneus`), which are inherently
  gray-matter-only and convoluted, giving a harder, more anatomically
  realistic detection target. Ground truth for the comparison is a
  SynthSeg segmentation of the MNI152 template itself (not a
  population union across subjects, which was found to smooth back out
  into an AAL-like blob under inter-subject registration variance).
  Adds a new boundary-distance metric (mean surface distance +
  Hausdorff distance, `experiments/compare_ground_truth_boundary.py`)
  alongside the existing Dice/ROC-AUC/PR-AUC, to directly measure
  boundary-tracking accuracy rather than just bulk overlap. ANTs tracks
  the true GM boundary most closely (5.47mm mean surface distance),
  FSL FLIRT-only close behind (6.46mm); FSL FLIRT+FNIRT's Dice
  collapses (0.017) despite having the highest ROC-AUC of the three,
  with boundary distance roughly 3x worse (17.94mm) — indicating its
  warp retains discriminative signal but doesn't spatially anchor it to
  the correct convoluted cortical shape.
- Added **cluster-size-aware spike filtering**: `get_spike_mask()` now
  only median-repairs/biharmonic-inpaints a connected cluster of
  spike-thresholded voxels when its size is at or below
  `--spike-max-cluster-voxels` (new flag; default auto-derived from the
  MRSI acquisition's native voxel size — 6 voxels at ~5.0mm/3T-like
  resolution, 9 voxels at ~3.4mm/7T-like resolution). Previously every
  voxel above the `--spikepc` percentile threshold was filtered
  regardless of how large or spatially coherent its cluster was, which
  could remove genuine focal signal (a real, spatially uniform metabolic
  abnormality reads identically to a spike artifact under a flat
  per-voxel threshold). The default cutoffs were derived from a real
  spike-cluster-size survey: the 90th-percentile connected-cluster size
  across 1075 3T metabolite maps (BioPsych-Project + Mindfulness-Project)
  and 445 7T metabolite maps (22q11-Project).
- Added a new **Voxel-Based Detection Benchmark** page
  (`docs/vba_benchmark.md`), validating whether MRSIPrep's three
  registration backends (ANTs, FSL FLIRT-only, FSL FLIRT+FNIRT) can
  recover a known, deliberately-injected metabolic abnormality via
  `randomise` VBA, using the cluster-size-aware spike filter above. ANTs
  has the best detection power on both tested metabolites (CrPCr/
  Precuneus, GluGln/Thalamus); FSL FLIRT+FNIRT is competitive with ANTs
  on CrPCr but collapses to near-chance on GluGln/Thalamus, consistent
  with FNIRT's nonlinear warp mattering most for small deep structures.
- Expanded the `mrsiprep.workflows.*` entry-point docstrings (all
  `run_*_workflow` functions, `prepare_anatomical`,
  `segment_t1_fuzzy_cmeans`, `create_brain_csf_t1`,
  `collect_recordings`, and their `*Result` dataclasses) from one-line
  summaries to full parameter/return/raises documentation, so the API
  Reference page (below) matches fMRIPrep's depth instead of showing
  mostly bare signatures.
- Added an fMRIPrep-style **API Reference** page (`docs/api.md`), built
  with Sphinx `autodoc`/`autosummary` over `mrsiprep.workflows.*`,
  `mrsiprep.registration.*`, `mrsiprep.interfaces.*`, `mrsiprep.mrsi.*`,
  `mrsiprep.tissue.*`, `mrsiprep.parcellation.*`/`mrsiprep.connectivity.*`,
  and `mrsiprep.io.*` — for anyone calling mrsiprep's pipeline stages
  directly from Python (`import mrsiprep`) rather than through the CLI.
  Added short docstrings to previously-undocumented top-level entry
  points (`run_participant_workflow`, `run_mrsi_workflow`,
  `run_tissue_workflow`, `run_parcellation_workflow`,
  `run_connectivity_workflow`, `prepare_anatomical`, and their
  `*Result` dataclasses) so the generated pages are useful rather than
  bare signatures. The docs build now installs the full scientific stack
  (numpy/scipy/nibabel/nilearn/nipype/etc., no `antspyx`, which mrsiprep
  never imports at module level) via `docs/requirements.txt`, on top of
  the existing dependency-light CLI-reference build.
- Reran the `--nthreads` scaling runtime benchmark (3T/7T, 8/12/16/32
  threads) with all 8 runs executed strictly sequentially and in
  isolation, to rule out cross-run resource contention affecting the
  timings (a prior run showed slightly more thread-count variation, run
  under less controlled conditions). Under isolation, runtime is
  essentially flat across the whole thread range at both field strengths
  (3T: 300-318s, ~6% spread; 7T: 1227-1235s, under 1% spread), confirming
  more than ~8 threads per subject gives negligible benefit. See
  `docs/benchmarks.md`.
- Added a transform-type table to the Registration Frameworks benchmark,
  documenting exactly what runs at the MRSI→T1w and T1w→MNI stages for
  each of the three compared configurations (ANTs rigid+affine+SyN vs.
  affine+SyN; FSL FLIRT-only affine; FSL FLIRT+FNIRT affine+deformable
  for MRSI→T1w only, since `--fsl-deformable` does not affect the
  T1w→MNI stage, which stays FLIRT affine-only for both FSL variants).
  See `docs/benchmarks.md`.
- Replaced the Registration Frameworks benchmark's mask-based "outside
  brain" voxel-count metric with a **signal-weighted leakage** metric
  (fraction of resampled CrPCr signal *mass*, not raw voxel count, falling
  outside the reference brain mask). The mask-based metric, while an
  improvement over its own predecessor, over-penalized FSL FLIRT+FNIRT
  specifically: nearest-neighbor-resampling a binary coverage mask
  through FNIRT's nonlinear warp locally dilates the mask's footprint
  independent of true registration accuracy. Weighting by actual signal
  magnitude removes this artifact; under the corrected metric, ANTs has
  the least leakage at both field strengths, followed by FSL FLIRT-only,
  with FSL FLIRT+FNIRT leaking the most signal mass of the three — the
  opposite ranking of FNIRT vs. FLIRT-only that the mask-based metric had
  shown at 7T. See `docs/benchmarks.md`.
- Corrected the Registration Frameworks benchmark's "outside brain mask"
  metric: it now resamples the native-resolution MRSI acquisition
  brainmask with nearest-neighbor interpolation and requires CRLB ≤ 20
  (mrsiprep's own `--crlb-max` default) rather than treating any nonzero
  resampled signal as "covered" — the previous signal-based metric
  overstated leakage by counting linear/spline interpolation smear at the
  brain boundary as real coverage. Also added a wall-clock runtime
  comparison (ANTs vs. FSL FLIRT vs. FSL FLIRT+FNIRT, 3T vs. 7T) to the
  same benchmark section, showing FNIRT's substantial extra cost
  (especially at 7T: ~53 min vs. ~27 min for ANTs vs. ~11 min for
  FLIRT-only). See `docs/benchmarks.md`.
- Added an FNIRT deformable stage to the FSL registration backend for
  MRSI→T1w (`--fsl-deformable`, **on by default** when
  `--registration-backend fsl` is selected; `--no-fsl-deformable` reverts
  to FLIRT-only), plus `--fsl-fnirt-warpres` (auto-computed from the MRSI
  reference's own native voxel size when unset) and `--fsl-fnirt-lambda`.
  Also fixed FLIRT's own defaults for this pipeline
  (`--fsl-cost` now `corratio`, seeded from the image's qform/sform frame
  with `-nosearch`): FLIRT's previous defaults (`mutualinfo`, unrestricted
  search) were found to reliably diverge on the small, low-contrast MRSI
  reference maps used here. `registration_t1_target=brain-csf` is now
  accepted under `--mode mni-norm` too (previously restricted to `brain`/
  `raw` with no technical justification — SynthSeg parcellation always
  parcellates the raw T1w directly, independent of the registration
  target). See `experiments/registration_backend_benchmark.py` for the
  validation comparing backends and targets on real 3T/7T subjects.
- Split `--longitudinal` subject-template normalization out of "MNI
  Normalization Usage" into its own
  [Longitudinal (Subject-Template) Normalization](usage_longitudinal.md)
  page, alongside `mni-norm`/`parc-con`, with the full algorithm (subject
  template construction, template→MNI registration, per-session transform
  composition), execution order/caching behavior, and derivative layout.
- Added `--mode midas`: a MIDAS-faithful processing pipeline (Maudsley et al.
  2006) using fuzzy c-means tissue segmentation, PSF-convolved tissue
  fractions, rigid MRSI→T1 registration, and per-parcel Eq. 4 pure-GM/pure-WM
  regression in place of PETPVC voxelwise partial-volume correction. Always
  uses SynthSeg parcellation and its own fuzzy c-means segmentation
  (`--tissue-backend` is ignored in this mode).
- Added an FSL registration backend (`--registration-backend fsl` /
  `flirt-fnirt`) as an alternative to the default ANTs backend: FLIRT affine
  registration for both MRSI→T1w and T1w→MNI (no deformable/FNIRT stage).
  New flags `--fsl-mrsi-to-t1-dof`, `--fsl-mrsi-to-t1-init`,
  `--fsl-t1-to-mni-dof`, `--fsl-cost` configure it; `--ants-mrsi-to-t1-transform`
  and `--ants-t1-to-mni-transform` expose the equivalent ANTs transform
  presets (unchanged defaults). `--longitudinal` currently requires the ANTs
  backend. Docker CPU image now keeps the full FSL tree (FLIRT/FNIRT need
  their schedule/configuration data, not just FAST's binary).
- Failed-recording console output no longer dumps the full exception text
  and traceback at `--verbose 2` (some failures, e.g. a `recon-all`/Chimera
  subprocess error, embed hundreds of lines of captured subprocess stdout in
  their exception message). Console now shows a one-line summary at every
  verbosity level and the full traceback only at `--verbose 3`; the
  per-recording logbook (`sub-*/ses-*/logs/*_desc-mrsiprep_log.txt`) always
  gets the full exception text and traceback regardless of `--verbose`, so
  nothing is lost — added `Debug.exception()` for this.
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
- Added `--longitudinal` subject-template normalization: for multi-session
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

# Changelog

## 1.15.1

### Runtime tab

- **Each step now reports an outcome beside its duration**, which a
  duration alone could not convey:
  - `PROC` -- computed during this run.
  - `REUSED` -- every output already existed and was reused because
    `--overwrite` was not passed. The step ran but did no work.
  - `N/A` -- the configuration never requested this step
    (`--no-pvc`, `--t1-correction none`, `--write-connectivity` unset),
    shown with the reason.
  - `FAILED` -- the step raised.

  "Skipped" previously conflated the middle two, which answer different
  questions: one is "why was this run fast", the other "why is this
  output missing".
- **MRSI-to-T1w and T1w-to-template registration are reported
  separately**, in the console step list and in the Runtime tab. They are
  independent registrations with different failure modes and very
  different costs, and one combined line hid which of the two a slow run
  was spending its time in.

## 1.15.0

### QC report

- **Tabs reordered and renamed** to follow the pipeline: MRSI Raw QC,
  MRSI PVC, Spike Filter, Anatomical, T1-space alignment, Template-space
  alignment, Coverage, Parcellation, Connectivity, MRSinMRS, PrepParams,
  Runtime, Outputs. `Preproc` is now **PrepParams**,
  `Coverage & Alignment` is **Coverage**, and `MNI-space alignment` is
  **Template-space alignment** (which now names the exact template and its
  resolution in mm).
- **New MRSI PVC tab**, when partial-volume correction ran: one
  10-slice axial montage per metabolite, at the same slices as MRSI Raw
  QC so the two can be compared by flipping between them. Omitted under
  `--no-pvc`, where the maps are identical to the uncorrected ones.
- **Coverage tab** is ranked by `qc_valid_fraction` (worst first) instead
  of `anatomical_coverage_percent`, and states the per-voxel thresholds
  actually in force for the run rather than a summary sentence.
- **Anatomical coverage** is shown as 10 equally-spaced axial slices
  instead of a triplanar view.
- **Parcelwise CRLB quality** is one metabolite x slice grid over the
  normalization template, semi-transparent so anatomy reads through. This
  replaces the glass-brain projection, which collapsed the volume onto
  three planes and so could not distinguish a deep unreliable parcel from
  a superficial one.
- **Outputs** is a `tree`-style listing of the recording's own derivative
  directory, excluding `reports/`.
- Tables sort on header click; the report title carries the BIDS dataset
  name.

### Fixes

- **Finished recordings now display DONE rather than RUNNING** in the
  parallel status table. The listener discarded messages still queued at
  shutdown, and the worker's completion message could be lost in transit
  entirely; the parent now asserts each outcome from its own future.
- **`--overwrite` now forces MRSI resampling to recompute.** Every other
  cached step (tissue segmentation, filtering, PVC, registration,
  subject templates) already treated `--overwrite` as "recompute
  everything" alongside its own specific flag; `mrsi/resampling.py` was
  the sole exception, honouring only `--overwrite-transform`. A run with
  `--overwrite` therefore kept stale resampled maps.

## 1.14.0

- **Breaking: `--mni-resolution` is removed; resolution is now a modifier
  on `--output-spaces`.** Following fMRIPrep's convention, each requested
  space may be qualified individually:

  ```bash
  --output-spaces MNI152NLin2009cAsym:res-2 T1w
  ```

  `res-` accepts an integer millimetre value, `res-origres` (MRSI native,
  the default) or `res-t1wres`. A single global flag could not express
  different resolutions for different spaces, which became a real
  limitation now that the template is no longer hard-wired to MNI.

  Migration: `--mni-resolution 2mm` becomes
  `--output-spaces MNI152NLin2009cAsym:res-2`; `--mni-resolution origres`
  is the default and can simply be dropped.

- **Breaking: three flags renamed** from MNI-specific to template-generic,
  since the target space is no longer necessarily MNI:

  | old | new |
  | --- | --- |
  | `--ants-t1-to-mni-transform` | `--ants-t1-to-template-transform` |
  | `--fsl-t1-to-mni-dof` | `--fsl-t1-to-template-dof` |
  | `--overwrite-mni-reg` | `--overwrite-template-reg` |

  No aliases are kept, matching how `--mode` and `--parcellation-mode mni`
  were handled. The built-in `imaging-neurosci-2026` preset is updated;
  custom preset JSON files using the old keys will need the same edit.

## 1.13.0

- **MNI outputs are now genuinely in the space their filenames claim.**
  MRSIPrep resampled into `nilearn.datasets.load_mni152_template()` --
  ICBM152 2009 release *a*, per nilearn's own documentation -- while
  labelling every output `space-MNI152NLin2009cAsym`, i.e. release *c*.
  The reference template now comes from TemplateFlow, so the label is
  correct and derivatives genuinely share a space with fMRIPrep outputs
  and TemplateFlow atlases.

  **This changes MNI-space output grids** (origin moves from
  `(-98,-134,-72)` to `(-96,-132,-78)`, matching the 2009cAsym
  reference). Regional values shift too, but by *less than the
  pipeline's own run-to-run variation*: median 1.5% vs a 2.2% noise
  floor measured by re-running the same image twice. Existing analyses
  do not need re-running on account of this.

  Also brought into line: the signal-leakage and ventricle QC masks,
  which came from FSL's `$FSLDIR` standard directory -- the
  MNI152NLin6Asym lineage, a different space again from the data being
  checked. They now use the same template the run normalizes into, with
  the FSL copy kept only as a fallback.

- **A single template provider** (`mrsiprep/config/templates.py`)
  replaces six scattered `load_mni152_template()` calls, so the target
  space is decided in one place -- the hook a non-MNI template would
  need. Templates are pre-fetched at image build time with
  `TEMPLATEFLOW_HOME` pinned, so runs remain fully offline (verified
  with `docker run --network none`).

- **Removed the dead `Registration` facade** from
  `interfaces/ants.py`. Nothing instantiated it, and it behaved
  differently from the live module-level functions (always wrapping
  `type_of_transform` in `antsRegistrationSyN[...]`, no CLI fallback).

## 1.12.0

- **Nucleus is now explicit, and non-proton MRSI is a first-class case.**
  New `--nucleus` (or a `Nucleus` field in `mrsinmrs.json`'s
  `CommonMetadata`) declares which nucleus a dataset was acquired with;
  it is recorded in the QC report and `provenance.json`. Nucleus
  definitions live in the new data-only `mrsiprep/config/nuclei.json`
  (¹H, ³¹P, ²H ship), so supporting another nucleus is a JSON edit rather
  than a code change -- see the new `docs/extending.md`.

  Voxel-quality thresholds and metabolite alias spellings are now
  per-nucleus rather than global. **Proton behaviour is unchanged**: ¹H
  keeps exactly the previous `snr_min=4.0 / linewidth_max=0.1 /
  crlb_max=20.0` and the same alias table, now sourced from the JSON.

  ³¹P and ²H ship *no* curated thresholds on purpose: their SNR regimes
  differ substantially from proton, so MRSIPrep refuses to run without
  explicit `--snr-min/--linewidth-max/--crlb-max` rather than silently
  applying proton values. Contributing citation-backed defaults is
  welcome.

  Precedence for the thresholds is: explicit CLI flag > `--config-preset`
  > nucleus defaults. `config/defaults.py`'s `QUALITY_DEFAULTS` and
  `METABOLITE_ALIASES` remain importable as the proton values.

- **Contributor documentation.** New `CONTRIBUTING.md` (container-based
  dev/test loop, the gitignored-`tests/` gotcha, CI expectations), plus
  `docs/architecture.md` (package responsibilities, config resolution
  order, the output-naming contract) and `docs/extending.md` (worked
  recipes for adding a nucleus, a tissue backend, or a parcellation
  backend).

- **Backend selection is now a registry rather than an if/elif chain.**
  `TISSUE_BACKENDS` (`workflows/tissue.py`) and `PARCELLATION_BACKENDS`
  (`workflows/parcellation.py`) map a name to a callable; adding a
  backend means adding an entry, and an unknown name errors listing what
  is registered.

- **`workflows/participant.py` split** (863 lines) into `preflight.py`
  (pre-run inventory and startup table), `steps.py` (the `_step_*`
  stages), and `participant.py` (orchestration). Pure code movement --
  `participant.py` re-exports the moved names, so existing imports keep
  working. `BIDSLayout.from_config()` replaces nine identical
  construction sites and carries the run's nucleus aliases.

- **Several parcellations in one run.** `--chimera-scheme`,
  `--chimera-scale`, `--chimera-grow`, and `--atlas` now each accept a
  comma-separated list, the same syntax Chimera's own
  `--parcodes`/`--scale`/`--growwm` use. The lists combine as a cross
  product, so `--chimera-scheme A,B --chimera-scale 1,3` builds four
  parcellations off a **single** preprocessing pass -- `recon-all` and
  Chimera each run once for the whole set, with registration, PVC, and
  resampling shared.

  Every parcellation gets its own regional table, metabolite-profile NPZ,
  profile estimation, and connectivity matrix, each keyed by atlas and
  scale so they never collide. The QC report stays one file per
  recording, gaining one Parcellation section per parcellation.

  Notes:
  - The cross product is a *request*, not a guarantee: `--chimera-scale`
    only applies to multi-resolution (Lausanne `L` cortex) schemes, so a
    non-multi-resolution scheme yields one parcellation however many
    scales are listed. Combinations Chimera doesn't produce are logged
    and skipped rather than failing the run.
  - When several `--chimera-grow` values are requested, the growth
    distance is added to the output names to keep the variants apart.
    Single-value runs are unaffected and keep byte-identical paths.
  - `provenance.json`'s `outputs` gains a `parcellations` list carrying
    every parcellation's derivatives. The existing singular keys
    (`regional_table`, `metprofiles`, `connectivity`, `atlas_mrsi`) still
    point at the first parcellation, so existing consumers keep working.
  - `--chimera-scale`/`--chimera-grow` are stored as given rather than
    coerced to `int`, so configs and presets round-trip unchanged; both
    bare integers (as in the shipped presets) and `scaleN` are accepted.

## 1.11.0

- **Removed `--mode`/`--processing-mode`.** `parc-con` was never a
  fundamentally different pipeline from `mni-norm` -- it ran everything
  `mni-norm` ran, plus a few optional extras. `--parcellation-mode`
  (`synthseg`/`chimera`/`atlas`) is now the sole switch for how much of
  the pipeline runs: `synthseg` (the new default) is the lighter-weight
  path; `chimera`/`atlas` additionally run full parcellation. Every other
  behavior (tissue backend, PVC, connectivity matrix, metabolite
  profiles) is controlled independently by its own already-existing
  flag, as it always should have been. `--mode`/`--processing-mode` is
  now a hard, unrecognized-argument error.

  Bundled with this, three real behavior changes (not just renames):
  - Regional metabolic profile estimation and the per-parcel metabolite
    NPZ export now run unconditionally for every recording, regardless
    of `--parcellation-mode` (previously `mni-norm`-equivalent runs
    skipped both entirely). Only the connectivity *matrix* itself stays
    behind `--write-connectivity`.
  - The preflight "Tissue" warning for `--tissue-backend existing` with
    an incomplete CAT12 map now applies regardless of
    `--parcellation-mode` (previously only checked under what used to
    be `parc-con` mode).
  - `--tissue-backend synthseg-fast`'s SynthSeg-brain path/mask
    override is now unconditional, regardless of
    `--registration-t1-target` (previously only applied when the
    target was `brain`, unless what used to be `parc-con` mode was
    also set) -- this also fixes a pre-existing gap where a
    `mni-norm`-equivalent run silently ignored `--tissue-backend`
    entirely and always forced `synthseg-fast`.
  - `--check-external-libs`'s required-tool list is corrected to key
    `fast`/`petpvc` off `--tissue-backend`/`--no-pvc` directly rather
    than off the old mode bundle, so a `synthseg`-parcellation run now
    correctly lists them as required.

## 1.10.1

- **Fixed the SynthMRSI-Project quickstart's `unzip` instructions**
  (`usage_basic.md`, `PUBLIC_DATASET.md`). The published zip has no
  top-level wrapper folder -- its contents sit flat at the archive root
  -- so the previously documented plain `unzip SynthMRSI-Project.zip`
  scattered files into the current directory instead of a
  `SynthMRSI-Project/` directory, breaking the demo's `docker run`
  mounts. Now uses `unzip SynthMRSI-Project.zip -d SynthMRSI-Project`.

## 1.10.0

- **Removed `--mode midas`.** The MIDAS-faithful pipeline (fuzzy c-means
  tissue segmentation, PSF-convolved tissue fractions, rigid MRSI→T1
  registration, and per-parcel Eq. 4 pure-GM/pure-WM regression) is no
  longer available; only `mni-norm` and `parc-con` remain. Removed
  `mrsiprep.tissue.fuzzy_cmeans`, `mrsiprep.tissue.psf`, and
  `mrsiprep.parcellation.tissue_regression` along with their call sites.

- **Added `--reports-only`,** which reuses every already-completed step's
  output derivatives as-is (tissue segmentation, registration,
  parcellation, PVC, etc.) and only regenerates QC tables, figures, and
  `desc-report.html`. Fails a recording with a clear error, rather than
  silently recomputing, if a required upstream derivative is missing. Runs
  the same per-recording step sequence directly, bypassing the Nipype
  node cache entirely, so it isn't affected by cache staleness/hashing and
  always produces a genuinely fresh report.

- **Added a Runtime tab to the per-recording HTML report,** with real
  per-step wall-clock timing (tissue segmentation, registration, PVC,
  parcellation, connectivity, etc.) and the `nproc`/`nthreads` context for
  the run. New output: `reports/coverage/*_desc-runtimeqc.json`
  (`mrsiprep.io.naming.runtime_metrics_derivative`).

- **Tightened spike-filter repair.** `get_spike_mask()` now restricts its
  percentile threshold and resulting spike mask to brain-mask voxels only
  (`--spike-mask`-equivalent behavior, matching the original
  mrsitoolbox's `bnd_np` parameter, which this port had never exposed),
  and gained a z-score safety net (`--spike-extreme-zscore`, default
  `4.0`): a repaired cluster larger than `--spike-max-cluster-voxels` is
  still repaired, rather than exempted as real focal signal, if its mean
  intensity is an implausible outlier against the map's own inside-brain
  mean/std. Large spike clusters are just as likely as small ones to be
  extreme-intensity acquisition artifacts, so cluster size alone was
  letting some genuinely broken clusters through unrepaired.

- **Renamed report tabs**: "MRSI QC" is now "MRSI Raw QC" (raw
  pre-pipeline metabolite maps and their QC, now including the ventricle
  visibility panel below); "Acquisition" is now "MRSinMRS", its table
  gained a Unit column, and the broken sequence-citation hyperlink was
  removed.

- **Fixed connectivity matrix export** to also write a labeled
  `*_desc-connectivity_matrix.tsv` (parcel-name row/column headers)
  alongside the existing `.npz`, which was previously the only matrix
  output.

- **Clarified T1w-space signal leakage reporting**: the T1w-space
  alignment tab now explains explicitly when leakage wasn't computed
  (T1w-space leakage requires `--output-mrsi-t1w`) instead of silently
  omitting the section, so its absence isn't mistaken for a bug.

- **Added a native-space ventricle visibility check to the MRSI Raw QC
  tab,** run before any T1w coregistration touches the data. A cheap,
  prior-only placement (translation + per-axis scale from brainmask
  centroid/extent, no iterative registration) warps FSL's Harvard-Oxford
  lateral-ventricle prior into each recording's own native MRSI grid;
  a local darker-than-surroundings threshold then detects whatever
  actually looks like ventricle in each metabolite's own raw signal, and
  the slice with the most detected voxels is rendered with the outline
  for visual inspection. Deliberately not reduced to a single pass/fail
  metric -- a naive summary ratio was tried and found to invert
  direction on real data, so the outline itself is the QC signal, not a
  derived score. All metabolites are laid out in a single combined
  montage, at most 5 per row (e.g. 9 metabolites -> 5 columns x 2 rows),
  rather than one image per metabolite. Requires `FSLDIR` and the
  Harvard-Oxford atlas data (bundled in the standard image); skipped
  gracefully, with no new section, when unavailable. New output:
  `reports/coverage/figures/*_ventricle-qc.png`.

- **Added a per-metabolite signal leakage metric to the standard
  coverage report.** Reuses the signal-weighted leakage metric from the
  [Registration Frameworks](benchmarks.md) benchmark (fraction of
  CRLB-passing signal mass falling outside the reference brain mask) and
  now computes it automatically for every recording, not just that
  benchmark: against the MNI152 standard brain mask for the default
  MNI-space output, and against the T1w reference brain mask when
  T1w-space output is also requested (`--output-mrsi-t1w`). New outputs:
  `confounds/*_desc-leakageqc.tsv` and a "Signal Leakage" table in
  `reports/coverage/*_desc-report.html`. Skipped (no new files) when
  neither space is available, e.g. `--registration-t1-target raw` with
  no MNI output.

## 1.9.1

- Trimmed the [Registration Frameworks](benchmarks.md) benchmark's
  interpretation into a concise Conclusions section.

## 1.9.0

- **Added optional protocol-level T1 saturation correction
  (`--t1-correction {none, literature}`, default `none`).** Corrects
  metabolite maps for incomplete T1 relaxation recovery using the
  steady-state spoiled-gradient-echo signal equation, TR/flip angle read
  from a dataset-level `mrsinmrs.json`, and a curated literature T1 value
  per metabolite per field strength (`mrsiprep/config/t1_literature.json`;
  editable data-only configuration; entries marked `todo` raise an explicit
  error if requested). Purely additive/opt-in: the
  default `none` produces byte-identical output to before this change. New
  outputs when enabled: `mrsi/orig-t1corr/*_desc-signalt1corr_mrsi.nii.gz`,
  `confounds/*_desc-t1corr.tsv`, a new QC report, and a `t1_correction`
  provenance block. See `--t1-correction-water-status` for handling
  already water-referenced inputs, and
  [T1 Saturation Correction](usage_t1_correction.md).

- Anonymized the [Cross-Site/Cross-Sequence Regional Profile
  Reproducibility](cross_sequence_benchmark.md) page: the two compared
  datasets are now referred to as `Lausanne3T-FID`/`Lausanne3T-ECCENTRIC`
  rather than by project name, with participant-ID-prefix and
  clinical-group details removed.

## 1.8.0

- **Breaking: consolidated per-voxel confound outputs into a single
  `confounds/` folder.** CRLB, SNR, FWHM/linewidth, spike masks, QC masks,
  the brain mask, and GM/WM/CSF tissue-fraction probsegs previously landed
  in `qmasks/`, `anat/tissue/`, or scattered alongside the actual signal
  maps in `mrsi/orig|t1w|mni/` depending on which quantity and space; all
  now live under `<out>/mrsiprep/sub-*/ses-*/confounds/`, one flat folder,
  distinguished by the existing `space-*`/`met-*`/`desc-*` filename
  entities (unchanged) rather than by folder. `mrsi/orig|t1w|mni/` now
  contain signal maps only. Existing derivative trees from prior runs are
  not migrated automatically; rerun with `--overwrite` (or the relevant
  step-specific `--overwrite-*` flag) to regenerate under the new layout.

- **Breaking: `--mni-resolution` now defaults to `origres` (MRSI native
  resolution) instead of `t1wres`.** Resampling MRSI signal onto a template
  grid finer than its own native acquisition resolution doesn't add real
  spatial information and implies a spatial precision the data never had;
  `origres` also matches the resolution mrsiprep's own spatial-smoothness
  benchmark evaluates registration/resampling at. Threaded the MRSI
  reference through the parcelwise QC-figure atlas resampling and the
  longitudinal per-session T1w-to-MNI composition so both resolve `origres`
  correctly instead of raising; the shared subject-template-to-MNI stage in
  `--longitudinal` mode (which spans multiple sessions and has no single
  well-defined native resolution) continues to use `t1wres` regardless of
  this default. Existing scripts/pipelines that rely on the previous
  T1w-resolution default should pass `--mni-resolution t1wres` explicitly.

- **Breaking: renamed two native-space MRSI signal derivatives so their
  filename always starts with `signal`, distinguishing the actual
  metabolite data from confound maps at a glance.** `mrsi/orig/`'s
  spike-filtered map is now `desc-signalspikefilt` (was `desc-preproc`);
  `mrsi/orig-pvc/`'s final PVC-corrected map is now `desc-signalpvc` (was
  `desc-pvc`) so it's unambiguous that the file is metabolite signal, not
  a CRLB/SNR/FWHM confound, and that it specifically underwent PVC.
  PETPVC's own raw RBV output -- previously kept as a permanent
  `desc-petpvcraw` derivative alongside `desc-pvc` in `mrsi/orig-pvc/` --
  is now a `--work-dir` scratch file instead, since nothing reads it back
  and it exists only so mrsiprep's own overshoot/negative-value clipping
  (applied on top of PETPVC's output to produce the final `desc-signalpvc`
  map) can be inspected by diffing against it when `--work-dir` is kept.


- Relabeled `docs/vba_benchmark.md`'s two ANTs configurations from
  "ANTs (SyN)" / "ANTs (no SyN)" to **ANTs (R+SyN)** / **ANTs (R+Aff)**
  throughout the page's prose, tables, and figures, for clarity and to
  avoid confusion with the differently-scoped genuine Rigid+Affine
  configuration on the Registration Frameworks benchmark page. Re-ran
  the CrPCr detection figures (`vba_detection_crpcr_4backend.png`,
  `vba_detection_crpcr_gm.png`) and the CrPCr/GluGln ROC/PR comparison
  (`vba_roc_pr_comparison.png`) from source, since matplotlib bakes
  labels into the rendered PNGs: a markdown-only text fix does not
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
  cluster was merely "visibly smaller" than the other three backends:
  the re-rendered figure shows it detects zero significant voxels at
  that slice.

## 1.7.6

- Corrected the Registration Frameworks benchmark's fourth registration
  configuration (`docs/benchmarks.md`): the previous release's "ANTs (no
  SyN)" reused mrsiprep's default MRSI→T1w transform with SyN dropped,
  which is **Rigid-only** at that stage (mrsiprep's default
  `antsRegistrationSyN[sr]` never computes a separate Affine stage there
  to fall back to), not a genuine Rigid+Affine configuration. This
  release replaces it with **ANTs (Rigid+Affine)**: a real second
  `antsRegistration transform="a"` run at the MRSI→T1w stage (new
  registration compute, 2 subjects × 2 targets), composed with the
  already-correct Rigid+Affine T1w→MNI transform (reused, no recompute
  needed there). Finding, now based on a genuine Rigid+Affine
  configuration: ANTs (Rigid+Affine) is the **second-leakiest** of all
  four configurations: 4.30% signal mass leakage at 3T and 4.73% at 7T,
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
  deformable warp dropped, no registration recompute. Also corrected a
  pre-existing error in that page's transform-stage table and prose:
  mrsiprep's default MRSI→T1w ANTs transform (`antsRegistrationSyN[sr]`)
  is **Rigid + SyN with no separate Affine stage**, not "rigid+affine+SyN"
  as previously described; the T1w→MNI stage (`[s]`) is the one that
  genuinely runs the full Rigid+Affine+SyN pipeline. The same correction
  was applied to `docs/vba_benchmark.md`, where the fourth backend added
  in an earlier release was likewise mislabeled "ANTs (rigid+affine
  only)", both pages now consistently use **ANTs (SyN)** / **ANTs (no
  SyN)**, with an explicit note on what "no SyN" means at each stage.
  Finding: unlike the VBA benchmark (where dropping SyN never clearly
  hurt, and sometimes helped, focal-signal detection), **the deformable
  SyN stage does real, measurable work for MNI-space leakage**: ANTs (no
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
  injection never spills into gray matter or CSF; no finer WM
  sub-parcellation is available from this pipeline, so a size-matched
  sphere is the closest fair-volume analogue to the two cortical
  targets). All three regions (medial GM, peripheral GM, deep WM) are
  injected simultaneously in the same CrPCr channel and reported per
  region. Finding: **deep WM has the highest ROC-AUC of all three
  regions for every backend** (0.84-0.97, vs. Precuneus's 0.77-0.86 and
  Postcentral's 0.52-0.60), but its Dice (0.05-0.06) is far below
  Precuneus's (0.32-0.42): strong group-level statistical separation
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
  a second, independent GM-only cluster, bilateral **postcentral gyrus**
  (primary somatosensory cortex, lateral convexity), alongside the
  existing medial Precuneus injection, in the same CrPCr channel, using
  the same per-subject bump amplitude. Reports Dice/ROC-AUC/PR-AUC/
  boundary-distance separately per region across all four registration
  configurations. Finding: **no backend detects the peripheral cluster
  at `alpha=0.05`** (Dice 0.000 everywhere, ROC-AUC 0.52-0.60, barely
  above chance), while the medial Precuneus injection is detected
  normally by every backend (Dice 0.32-0.43). Group-level statistics on
  the merged signal show a comparable mean group difference at both
  sites, but more than 2x higher inter-subject variability at the
  peripheral site (SD 138.3 vs. 62.5): the direct, measurable signature
  of registration/inter-subject-alignment accuracy being worse for a
  superficial gyrus than a deeper medial structure, independent of which
  of the four registration configurations is used.
- Added a fourth registration configuration, **ANTs (rigid+affine
  only)**, throughout the Voxel-Based Detection Benchmark
  (`docs/vba_benchmark.md`): both the original AAL-parcel comparison
  (CrPCr/Precuneus, GluGln/Thalamus) and the GM-precise boundary-tracking
  follow-up. It reuses the same MRSI→T1w/T1w→MNI registrations already
  computed for the full ANTs (rigid+affine+SyN) run: `antsRegistration`
  always writes the affine stage to its own independent transform file
  regardless of a later SyN stage, so the deformable warp can simply be
  dropped from the resampling chain with no registration recompute.
  Consistent finding across both metabolites and both ground-truth
  granularities: **ANTs affine-only matches or exceeds full ANTs SyN on
  every metric** (ROC-AUC, PR-AUC, Dice, boundary distance): the
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
  with boundary distance roughly 3x worse (17.94mm), indicating its
  warp retains discriminative signal but doesn't spatially anchor it to
  the correct convoluted cortical shape.
- Added **cluster-size-aware spike filtering**: `get_spike_mask()` now
  only median-repairs/biharmonic-inpaints a connected cluster of
  spike-thresholded voxels when its size is at or below
  `--spike-max-cluster-voxels` (new flag; default auto-derived from the
  MRSI acquisition's native voxel size: 6 voxels at ~5.0mm/3T-like
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
  and `mrsiprep.io.*`: for anyone calling mrsiprep's pipeline stages
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
  with FSL FLIRT+FNIRT leaking the most signal mass of the three, the
  opposite ranking of FNIRT vs. FLIRT-only that the mask-based metric had
  shown at 7T. See `docs/benchmarks.md`.
- Corrected the Registration Frameworks benchmark's "outside brain mask"
  metric: it now resamples the native-resolution MRSI acquisition
  brainmask with nearest-neighbor interpolation and requires CRLB ≤ 20
  (mrsiprep's own `--crlb-max` default) rather than treating any nonzero
  resampled signal as "covered": the previous signal-based metric
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
  `raw` with no technical justification: SynthSeg parcellation always
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
  nothing is lost. Added `Debug.exception()` for this.
- **Breaking:** `--metabolites` and `--ref-met` are now required, with no
  defaults. `--b0` (and the field-strength-dependent default metabolite
  lists it selected between) has been removed entirely: there is no
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
  their existing names. Cosmetic/additive only. No existing flag was
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
  only kept the four binaries mrsiprep directly invokes and missed it,
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

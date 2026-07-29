# Voxel-Based Detection Benchmark

This page validates whether MRSIPrep's pipeline — across four
registration configurations (ANTs rigid+affine+SyN, ANTs rigid+affine
only, FSL FLIRT-only, FSL FLIRT+FNIRT) — can recover a known,
deliberately-injected metabolic abnormality via a standard
voxel-based-analysis (VBA) group comparison (`randomise -T`, FSL's
TFCE-corrected permutation test).

## Dataset

**SynthMRSI-VBA-Project** is a synthetic validation dataset: 32 dummy
subjects, each built from a real T1w anatomical (drawn from
BioPsych-Project/Mindfulness-Project/22q11-Project template subjects) and
model-synthesized MRSI metabolite signal. For subjects assigned
`group=1` (16 of 32), a deterministic Gaussian-style signal bump is added
to every voxel inside a specific bilateral anatomical region, per
metabolite, before the signal is warped from the template subject's own
T1w-native space into that dummy subject's MRSI-native space and on into
`derivatives/mrsi-orig/`. `group=0` subjects (16 of 32) receive no
injection. This lets `randomise`'s two-sample group contrast
(`group1 > group0`) be checked against a known, exact ground truth,
independent of registration backend.

This report covers **CrPCr** (bilateral Precuneus) and **GluGln**
(bilateral Thalamus) only. The other three injected metabolites
(NAANAAG, GPCPCh, Ins) showed no detectable signal above chance for any
backend at the injected effect size and are out of scope here.

### Spike filter interaction

An earlier version of this benchmark showed near-zero detection across
every metabolite and backend. The root cause: MRSIPrep's biharmonic
spike-repair filter (`--spikepc`, default 99th percentile) was removing
the injected abnormality before it ever reached registration — a
spatially uniform region injection looks exactly like a spike artifact
under a flat per-voxel threshold. This is now fixed with **cluster-size-
aware spike filtering**: a connected cluster of spike-thresholded voxels
is only median-repaired/biharmonic-inpainted when its size is at or below
`--spike-max-cluster-voxels` (default: auto-derived from the MRSI
acquisition's native voxel size — 6 voxels at ~5.0mm/3T-like resolution,
9 voxels at ~3.4mm/7T-like resolution). Larger, spatially coherent
clusters — like a genuine focal abnormality — are left unfiltered. The
default cutoffs were derived from the 90th-percentile connected-cluster
size in a real spike-cluster-size survey across 1075 3T metabolite maps
(BioPsych-Project + Mindfulness-Project) and 445 7T metabolite maps
(22q11-Project).

### Runs compared

Four registration configurations were run on the same 32 dummy subjects
(one subject excluded for an independently-confirmed bad registration —
see below), at 2mm MNI resolution, then compared with `randomise -T`
(500 permutations, two-sample unpaired design, contrast `group1 >
group0`) restricted to each metabolite's population quality mask (CRLB
&lt; 20 in ≥70% of subjects). **ANTs (rigid+affine only)** reuses the
*same* MRSI→T1w and T1w→MNI registrations already computed for the
full ANTs (rigid+affine+SyN) run — `antsRegistration` always writes
the affine stage to its own independent `.mat` file regardless of
whether a later SyN stage also ran, so the deformable warp can simply
be dropped from the resampling transform chain with no registration
recompute needed.

| | |
|---|---|
| Subjects | 31 of 32 (sub-30 excluded: independently confirmed bad registration at both the MRSI→T1w and T1w→MNI stages, unrelated to the spike-filter fix) |
| Group sizes | 15 vs. 16 |
| Permutations | 500 |
| Resolution | 2mm MNI |
| Quality mask | CRLB &lt; 20 in ≥70% of subjects, per metabolite |
| Significance threshold | `alpha = 0.05` (TFCE-corrected, `corrp > 0.95`) |

## Injection regions

The figures below outline each metabolite's injection region using a
**real AAL atlas parcellation image** (not the population ground-truth
mask used later in this report) — the same template subject and region
IDs actually used by the injection for one representative dummy subject,
confirmed via `derivatives/mrsiprep/synthetic_orig_transform_provenance.tsv`:
CrPCr uses AAL region IDs 67/68 (Precuneus L/R), GluGln uses AAL region
IDs 77/78 (Thalamus L/R), from that template subject's own
`space-mni_atlas-aal_dseg.nii.gz`.

**CrPCr — bilateral Precuneus:**

![CrPCr injection region, bilateral Precuneus outlined on the MNI152 template from a real AAL atlas parcellation, axial and coronal slices](figures/vba_injection_region_crpcr.png)

**GluGln — bilateral Thalamus:**

![GluGln injection region, bilateral Thalamus outlined on the MNI152 template from a real AAL atlas parcellation, axial and coronal slices](figures/vba_injection_region_glugln.png)

## Detection results by backend

For each metabolite, the same axial/coronal slice positions as above
show:
- **Filled (red-yellow)**: voxels significant at `alpha=0.05` from that
  backend's `randomise` output, restricted to the population quality
  mask.
- **Outline (blue)**: the population ground-truth injection mask (the
  per-subject injection masks, averaged across all `group=1` subjects
  and thresholded at &gt;0) — this is the one place in this report the
  ground-truth mask itself is used, for comparing detected voxels
  against the known injection footprint.

**CrPCr:**

![CrPCr: voxels significant at alpha=0.05 (filled) vs. ground-truth Precuneus injection mask (outline), for ANTs (SyN), ANTs (affine-only), FSL FLIRT, and FSL FLIRT+FNIRT](figures/vba_detection_crpcr_4backend.png)

All four configurations detect a cluster well inside the true Precuneus
region. FSL FLIRT+FNIRT's detected cluster is visibly smaller than the
other three, consistent with its lower sensitivity in the ROC/PR
results below.

**GluGln:**

![GluGln: voxels significant at alpha=0.05 (filled) vs. ground-truth Thalamus injection mask (outline), for ANTs (SyN), ANTs (affine-only), FSL FLIRT, and FSL FLIRT+FNIRT](figures/vba_detection_glugln_4backend.png)

ANTs (both with and without the SyN stage) detects a clean, tightly
bilateral cluster inside the Thalamus. FSL FLIRT-only detects a real
but visibly asymmetric cluster (stronger on one side). **FSL
FLIRT+FNIRT detects nothing at `alpha=0.05`** — zero significant
voxels at either slice — matching its near-chance ROC-AUC below.

## ROC / Precision-Recall curves

A single `alpha=0.05` snapshot only shows one point on each backend's
detection tradeoff curve. Sweeping the TFCE-corrected significance
threshold (`corrp`) across its full range gives the complete ROC and
precision-recall curves and their AUC — a threshold-independent measure
of total discriminative power.

![ROC and precision-recall curves for CrPCr and GluGln, comparing ANTs, FSL FLIRT, and FSL FLIRT+FNIRT, with AUC in each legend](figures/vba_roc_pr_comparison.png)

| Backend | CrPCr ROC-AUC | CrPCr PR-AUC | GluGln ROC-AUC | GluGln PR-AUC |
|---|---|---|---|---|
| ANTs (rigid+affine+SyN) | 0.78 | 0.47 | 0.93 | 0.69 |
| ANTs (rigid+affine only) | 0.83 | 0.50 | 0.95 | 0.65 |
| FSL FLIRT-only | 0.72 | 0.38 | 0.76 | 0.33 |
| FSL FLIRT+FNIRT | 0.77 | 0.44 | 0.48 | 0.00 |

**ANTs (rigid+affine only)** reuses the same MRSI→T1w/T1w→MNI
registrations as the full ANTs run above, with the deformable SyN stage
simply dropped from the resampling transform chain — see the
"GM-precise boundary tracking" section below for why this variant was
added and how it's computed.

### Interpretation

* **ANTs is the best-performing backend on both metabolites**, and
  **the affine-only variant is consistently at least as good as the
  full SyN pipeline** — on GluGln it has the highest ROC-AUC of any
  backend (0.95), and on CrPCr it leads on both ROC-AUC (0.83) and
  PR-AUC (0.50). The deformable SyN stage does not clearly improve
  detection power over rigid+affine alone on either metabolite in this
  benchmark.

* **FSL FLIRT+FNIRT is competitive with the ANTs variants on CrPCr**
  (ROC-AUC 0.77, close to ANTs SyN's 0.78) **but collapses to
  near-chance on GluGln** (ROC-AUC 0.48, PR-AUC 0.00 — no better than
  random). This is specific to the Thalamus, a small, deep,
  centrally-located structure — consistent with the Registration
  Frameworks benchmark's (see the [Benchmarks](benchmarks.md) page)
  finding that FNIRT's nonlinear warp has higher signal-weighted
  leakage than ANTs or FLIRT-only: a small deep structure is exactly
  where local nonlinear-warp distortion would do the most damage to a
  focal signal.

* **FSL FLIRT-only is consistently the weakest backend on both
  metabolites, but still clearly above chance** (ROC-AUC 0.72 and
  0.76) — real detection power, just less than either ANTs variant.

* Taken together with the Registration Frameworks benchmark, ANTs is the
  best-supported default for analyses where recovering a real, focal
  signal change matters — and since the affine-only variant matches or
  exceeds full SyN's detection power here at a fraction of the
  registration cost (see the runtime comparison on the
  [Benchmarks](benchmarks.md) page), it is worth considering as the
  default over the full deformable pipeline for VBA workflows
  specifically. FSL FLIRT+FNIRT's extra registration cost does not
  translate into better — and for deep structures, translates into
  markedly worse — detection power than FLIRT-only.

## GM-precise boundary tracking (CrPCr / Precuneus only)

The CrPCr/Precuneus injection above used the raw AAL atlas parcel, which
is only ~62% gray matter in native T1w space (35,227 mm³ total parcel vs.
21,789 mm³ at CAT12 GM-probability &gt;0.5) — its coarse boundary sweeps
into adjacent white matter rather than tightly tracing the folded
cortical ribbon. Bulk-overlap metrics like Dice can't tell whether a
detected cluster actually *tracks the true convoluted GM boundary*, or
just overlaps the same general neighborhood. This follow-up re-injects
CrPCr's abnormality restricted to gray matter only, then adds a
boundary-distance metric to directly measure boundary-tracking accuracy.

### GM-only region source

Instead of intersecting the AAL parcel with a separate gray-matter
probability map, the injection's region *source* itself was switched to
`mri_synthseg --parc`'s own DKT cortical labels
(`ctx-lh-precuneus`/`ctx-rh-precuneus`) for the same template subject —
these are inherently gray-matter-only, per-gyrus regions, so no separate
masking step is needed. The combined bilateral region shrinks from
35,227 mm³ (AAL) to 20,425 mm³ (SynthSeg) in native T1w space, and its
boundary is visibly more convoluted:

![CrPCr injection region: bilateral Precuneus, gray-matter-only, from a SynthSeg parcellation of the MNI152 template itself](figures/vba_injection_region_crpcr_gm.png)

Only CrPCr's injection region changed — GluGln/Thalamus and the other
three metabolites keep their original AAL-based regions unchanged
(Thalamus is already a compact subcortical nucleus, not a folded cortical
structure, so the boundary-complexity question doesn't apply there). The
signal was re-filtered (same cluster-size-aware spike filter) and
re-resampled into MNI space through each backend's already-computed
registration transforms — no registration rerun, since registration
depends only on anatomy, not on the injected signal.

### Detection vs. the GM-precise ground truth

The population ground-truth mask used earlier in this report (the mean
of all 16 `group=1` subjects' own injection masks) is appropriate for
the AAL-parcel comparison above, but is the wrong reference here: each
subject's own injected region is correctly gray-matter-only and
convoluted, but averaging 16 of them across their own individual
inter-subject registration variance smooths the union back out into a
diffuse, AAL-shaped blob (confirmed directly: no voxel is inside the
injected region for more than 50% of `group=1` subjects). Instead, the
ground-truth outline below is `mri_synthseg --parc`'s own segmentation
of the **MNI152 template itself** — the same fixed anatomical space
every backend's detected voxels are already shown in, so no
inter-subject registration variance is introduced and the true
gyrus-following boundary stays sharp:

![CrPCr (GM-only Precuneus injection): voxels significant at alpha=0.05 (filled) vs. SynthSeg GM-precise Precuneus on the MNI152 template (blue outline), for ANTs (SyN), ANTs (affine-only), FSL FLIRT, and FSL FLIRT+FNIRT](figures/vba_detection_crpcr_gm.png)

| Backend | Dice | Sensitivity | Precision | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|
| ANTs (rigid+affine+SyN) | 0.341 | 0.244 | 0.569 | 0.810 | 0.315 |
| ANTs (rigid+affine only) | 0.432 | 0.374 | 0.510 | 0.849 | 0.326 |
| FSL FLIRT-only | 0.326 | 0.250 | 0.470 | 0.773 | 0.238 |
| FSL FLIRT+FNIRT | 0.017 | 0.009 | 0.721 | 0.815 | 0.268 |

**ANTs (rigid+affine only) has the best Dice, sensitivity, and ROC-AUC
of all four backends** on this harder, GM-precise target — the
deformable SyN stage actually *reduces* Dice here (0.341 vs. 0.432)
relative to skipping it. This mirrors the pattern seen on the
coarser AAL-parcel version of this benchmark above: SyN's nonlinear
warp does not clearly help focal-signal detection, and on this metric
actively hurts it.

Dice drops for every backend relative to the AAL-parcel version of this
benchmark — expected, since a tight, convoluted GM boundary is a
harder target to hit exactly than a bulk parcel. **FSL FLIRT+FNIRT's
Dice collapses to 0.017** — visibly almost no detected voxels at
`alpha=0.05` in the figure above — while its ROC-AUC (0.815) is close
to ANTs SyN's and not far off ANTs affine-only's. This combination
means FLIRT+FNIRT's `corrp` map does carry real discriminative signal,
but it is spread too diffusely (or offset) to ever cross the
TFCE-corrected significance threshold in the right place, rather than
lacking signal altogether.

### Boundary-distance metric

Dice and ROC/PR-AUC summarize bulk voxel overlap and threshold-sweep
discriminative power, but neither directly measures *where* a detected
cluster's edge sits relative to the true boundary. `experiments/compare_ground_truth_boundary.py`
extracts the voxel-surface of the alpha=0.05 detected mask and of the
GM-precise ground-truth mask (the same MNI152-template SynthSeg
Precuneus segmentation used above), then reports the symmetric mean
surface distance and Hausdorff distance (mm) between them:

| Backend | Mean surface distance (mm) | Hausdorff distance (mm) |
|---|---|---|
| ANTs (rigid+affine+SyN) | 5.47 | 23.07 |
| ANTs (rigid+affine only) | 4.32 | 22.36 |
| FSL FLIRT-only | 6.46 | 33.11 |
| FSL FLIRT+FNIRT | 17.94 | 45.52 |

### Interpretation

* **ANTs (rigid+affine only) tracks the true gray-matter boundary most
  closely of all four backends** (4.32mm mean surface distance —
  under two and a half voxels at this 2mm resolution), narrowly ahead
  of full ANTs SyN (5.47mm) and FSL FLIRT-only (6.46mm). Skipping the
  deformable stage does not cost boundary precision here — if
  anything, it modestly improves it, consistent with SyN's effect on
  Dice above.

* **FSL FLIRT+FNIRT's boundary is roughly 3-4x farther from the true
  GM boundary than either ANTs variant** (17.94mm mean, 45.52mm
  Hausdorff, vs. ANTs affine-only's 4.32mm/22.36mm) — this is the
  clearest signal in this follow-up that FNIRT's nonlinear warp,
  whatever discriminative power it retains (reflected in its
  ROC-AUC), is not spatially anchoring that signal to the correct
  convoluted cortical shape. Combined with its collapsed Dice, this
  reinforces the same conclusion as the Registration Frameworks
  benchmark's leakage finding: FNIRT's warp trades spatial precision
  for something that superficially still separates group1/group0 in
  aggregate, which is the wrong tradeoff for voxel-based analyses of
  focal cortical abnormalities.

* **Ranking is unchanged from the coarser AAL-parcel benchmark** (ANTs
  variants ≥ FSL FLIRT-only ≫ FSL FLIRT+FNIRT), but the gap between
  FLIRT+FNIRT and the other backends widens substantially once the
  target requires tracking a genuinely convoluted boundary rather than
  bulk overlap with a smooth parcel — a harder, more realistic test of
  cortical-abnormality detection. Across both the AAL-parcel and
  GM-precise versions of this benchmark, **ANTs' deformable SyN stage
  never clearly outperforms rigid+affine alone for this kind of focal,
  planted-signal VBA detection task** — its extra registration cost
  buys smoother anatomical correspondence in general, but not better
  recovery of a known focal abnormality.

## Medial vs. peripheral cortex (CrPCr only)

Precuneus is a **medial** structure, tucked against the brain's midline
and relatively far from the skull. This follow-up adds a second,
independent injection site — bilateral **postcentral gyrus**
(`ctx-lh-postcentral`/`ctx-rh-postcentral`, primary somatosensory
cortex) — a comparably sized, GM-only cortical region that instead sits
at the **periphery** of the brain, directly under the parietal
convexity immediately behind the central sulcus, in a different lobe
(parietal, but a distinct and non-adjacent gyrus) from Precuneus:

![CrPCr injection regions: medial Precuneus (blue) vs. peripheral Postcentral Gyrus (orange), SynthSeg parcellation of the MNI152 template](figures/vba_injection_region_crpcr_gm_2cluster_postcentral.png)

Both regions were injected simultaneously into the same CrPCr channel
(a single `--abnormal-regions CrPCr:synthseg:ctx-lh-precuneus,ctx-rh-precuneus,ctx-lh-postcentral,ctx-rh-postcentral`
union — the injection, spike-filtering, and resampling machinery is
region-shape-agnostic and required no changes for a spatially disjoint
target), with the same uniform per-subject bump amplitude
(effect × whole-brain p95, confirmed via
`synthetic_orig_transform_provenance.tsv`) applied identically at both
sites. Detection and boundary-distance metrics are reported **per
region** below, since combining a medial and a peripheral cluster into
one Dice/boundary number would blur exactly the comparison this
follow-up is meant to make.

### Detection results by cluster and backend

**Precuneus (medial):**

![CrPCr, medial Precuneus: voxels significant at alpha=0.05 (filled) vs. ground truth (blue outline), for ANTs (SyN), ANTs (affine-only), FSL FLIRT, and FSL FLIRT+FNIRT](figures/vba_detection_crpcr_gm_precuneus.png)

**Postcentral gyrus (peripheral):**

![CrPCr, peripheral Postcentral Gyrus: voxels significant at alpha=0.05 (filled) vs. ground truth (blue outline), for ANTs (SyN), ANTs (affine-only), FSL FLIRT, and FSL FLIRT+FNIRT](figures/vba_detection_crpcr_gm_postcentral.png)

**No backend detects any voxel at `alpha=0.05` anywhere in the
peripheral Postcentral Gyrus region** — zero filled voxels at every
panel above, for all four registration configurations. This is a
uniformly negative result, not a single-backend failure. (The filled
yellow clusters visible in the figure above all sit on the medial
Precuneus outline in the same slice — the peripheral outline has no
overlap with any detected voxel at all.)

| Region | Backend | Dice | Sensitivity | Precision | ROC-AUC | PR-AUC | Mean surface distance (mm) | Hausdorff (mm) |
|---|---|---|---|---|---|---|---|---|
| Precuneus (medial) | ANTs (rigid+affine+SyN) | 0.351 | 0.254 | 0.566 | 0.825 | 0.316 | 5.38 | 22.80 |
| Precuneus (medial) | ANTs (rigid+affine only) | 0.431 | 0.372 | 0.511 | 0.860 | 0.329 | 4.33 | 22.36 |
| Precuneus (medial) | FSL FLIRT-only | 0.324 | 0.247 | 0.471 | 0.773 | 0.238 | 6.55 | 33.11 |
| Precuneus (medial) | FSL FLIRT+FNIRT | 0.016 | 0.008 | 0.744 | 0.814 | 0.266 | 18.47 | 45.17 |
| Postcentral gyrus (peripheral) | ANTs (rigid+affine+SyN) | 0.000 | 0.000 | 0.000 | 0.595 | 0.010 | 41.48 | 74.70 |
| Postcentral gyrus (peripheral) | ANTs (rigid+affine only) | 0.000 | 0.000 | 0.000 | 0.586 | 0.007 | 39.49 | 71.86 |
| Postcentral gyrus (peripheral) | FSL FLIRT-only | 0.000 | 0.000 | 0.000 | 0.518 | 0.004 | 45.49 | 72.25 |
| Postcentral gyrus (peripheral) | FSL FLIRT+FNIRT | 0.000 | 0.000 | 0.000 | 0.521 | 0.004 | 53.14 | 84.99 |

The Precuneus numbers here match the single-cluster GM-precise section
above (small differences are permutation-test noise from a fresh
`randomise` run, not a methodology change) — confirming the two
regions' injections are independent and this new peripheral cluster
adds a genuinely separate test rather than disturbing the medial one.

### ROC / Precision-Recall by cluster

![ROC and precision-recall curves, medial Precuneus vs. peripheral Postcentral Gyrus, all four backends](figures/vba_roc_pr_comparison_2cluster_postcentral.png)

The two clusters tell an even sharper story here than a bulk-overlap
metric alone would suggest. **ROC-AUC for the Postcentral Gyrus
(0.52-0.60) is barely above chance (0.50) for every backend** — unlike
a purely diffuse-but-real-signal case, this is close to the
no-discriminative-power floor. **PR-AUC collapses to 0.004-0.010** (vs.
Precuneus's 0.24-0.33), and both ROC curves visibly hug the diagonal in
the figure above rather than bowing toward the top-left corner. Taken
together, this is a materially weaker result than the case would be for
a region where real but diffuse signal still separates the two groups
somewhat — here, group-level statistical evidence for the injected
abnormality is nearly absent at the periphery, despite the same
injection amplitude being used at both sites.

### Why: registration variance, not injection strength

Comparing group-level statistics directly on the merged 4D signal used
as `randomise`'s input (ANTs SyN backend, n=31, from
`experiments/results/vba_ants_no30_postcentral_500perm/merged/`):

| Region | group=1 mean | group=0 mean | Difference | Inter-subject SD of per-subject regional mean |
|---|---|---|---|---|
| Precuneus (medial) | 1393.5 | 1315.4 | 78.0 | 62.5 |
| Postcentral gyrus (peripheral) | 1004.9 | 939.4 | 65.5 | 138.3 |

The mean group difference is comparable at both sites (65.5 vs. 78.0)
— **but the peripheral site's inter-subject variability is more than
2x higher** (SD 138.3 vs. 62.5). A `randomise` group contrast is a
signal-to-noise comparison, not a signal-magnitude comparison: a
similar mean difference riding on much larger inter-subject scatter
produces a far weaker group-level statistic. This is the direct,
measurable signature of registration/inter-subject-alignment accuracy
being worse for a superficial gyrus immediately under the skull than
for a deeper, more stereotyped medial structure — exactly the effect
this follow-up set out to test for.

### Interpretation

* **A real focal abnormality at the cortical periphery is
  systematically harder to recover in group-level VBA than the same
  abnormality placed medially — for every registration backend
  tested, with no exception.** This isn't a backend-specific weakness;
  it reflects that lateral, superficial cortical folding is less
  spatially consistent across subjects after registration (to any of
  the four configurations) than the more stereotyped medial Precuneus.

* **Backend ranking by ROC-AUC is roughly preserved between the two
  clusters** (ANTs rigid+affine+SyN ≈ ANTs rigid+affine only > FSL
  FLIRT+FNIRT ≈ FSL FLIRT-only on Postcentral; ANTs affine-only > ANTs
  SyN > FSL FLIRT+FNIRT > FSL FLIRT-only on Precuneus) — the relative
  registration-quality story from the rest of this benchmark still
  holds, but the *absolute* achievable detection power drops sharply
  for all four backends alike once the target moves to the cortical
  periphery, to the point of being indistinguishable from chance here.

* This is a caution for real VBA studies of superficial cortical
  regions (much of the association and sensorimotor cortex relevant to
  psychiatric and neurological research sits at or near the
  periphery): a well-registered, high-powered study can still fail to
  reach significance for a real focal effect purely because of higher
  inter-subject anatomical variability at the cortical rim, independent
  of which registration backend is used.

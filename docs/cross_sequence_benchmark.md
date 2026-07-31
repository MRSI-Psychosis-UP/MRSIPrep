# Cross-Site/Cross-Sequence Regional Profile Reproducibility

The benchmarks on the other two pages validate MRSIPrep's registration and
detection performance on data it was built and tuned against — a real
3T/7T ECCENTRIC pair, and a synthetic ground-truth cohort. This page tests
something harder: whether MRSIPrep-derived regional metabolite profiles
reproduce on entirely independent real-world data — different subjects,
different scanners, different sites, and different MRSI sequences,
processed with the same pipeline and parcellation.

Because absolute metabolite units are not expected to agree across
different sequences and field strengths — scanner-, sequence-, and
reconstruction-dependent scaling and referencing choices affect the
overall signal level independently of true tissue concentration — this is
deliberately framed as a test of whether the **relative spatial pattern**
of regional metabolite levels reproduces across acquisitions, not whether
absolute values agree.

## Dataset

Two independently acquired real-world cohorts, merged into one group-level
MRSIPrep connectivity/profile archive
(`LPN-BioPsych-Project_atlas-chimeraLFMIHIFIS_scale3_desc-group_connectivity_mrsi.npz`):

| | LPN-Project | BioPsych-Project |
|---|---|---|
| `MRSI_SEQ` code | 0 | 1 |
| Participant ID prefixes | `CHUVA`, `CHUVL`, `CHUVF` | `CHUVUP`, `CHUVLFT` |
| n (healthy controls, after exclusion) | 12 | 15 |

Restricted to healthy controls (`Cohort == 'CTRL'`, equivalently
`Diag == 0` / `State == 0` — all three fields agree exactly on the same 28
subjects) specifically so the comparison isolates acquisition effects from
clinical-group composition; the full merged cohort's `MRSI_SEQ` does **not**
collapse onto diagnostic group (both sequences mix CTRL/ARMS/EPP/LOFT/EP
subjects elsewhere), so restricting to controls here is a deliberate choice
to compare like with like, not a workaround for a confounded design. Of 28
available controls, 1 was excluded for flagged spectral quality
(`exclude` or `exclude_noisy_metsim` in the archive's `covars` field),
leaving 27 (12 LPN-Project, 15 BioPsych-Project).

## Method

For each of the 5 metabolites (CrPCr, GluGln, GPCPCh, NAANAAG, Ins) and
each of the 203 parcels of the `chimeraLFMIHIFIS` scale-3 parcellation:

1. **Per-subject point estimate**: the median across the
   $K_{\mathrm{pert}}=50$ CRLB-perturbed draws in the archive's
   `metab_profiles_subj_list` array (shape `(subjects, parcels, nperm,
   metabolites)`) — MRSIPrep's uncertainty-propagated regional profile
   estimation, see the main docs' connectivity/profile documentation.
2. **GM-only filtering**: excludes only `brain-stem-midbrain` (203 → 202
   parcels) as not cleanly gray matter. This parcellation scheme contains
   no white matter parcels at all — cortex (`ctx-`), cerebellum (`cer-`),
   hippocampus (`hipp-`), subcortical nuclei (`subc-`), and thalamic
   nuclei (`thal-`) are all retained. A GM+WM follow-up is left for future
   work once a scheme with WM parcels is used.
3. **Sub-parcel merging**: parcels sharing the same anatomical root differ
   only by the Lausanne scheme's finer sub-parcellation index (e.g.
   `ctx-lh-superiorfrontal_1` through `_8` are the same gyrus at finer
   granularity, not eight distinct regions) — averaged into a single
   root-region value per subject. This collapses 202 GM parcels into **82
   root regions**.
4. **Group profile**: for each metabolite and root region, the mean (and
   95% CI, across subjects) within each cohort.
5. **Cross-cohort comparison**: Spearman correlation between the two
   cohorts' 82-region mean profiles, per metabolite — a threshold-
   independent, scale-free test of whether the two acquisitions rank
   regions the same way, deliberately insensitive to any absolute scale
   difference between them.

## Results

![Cross-sequence regional metabolic profile reproducibility, healthy controls, 82 GM root regions, all 5 metabolites, each cohort on its own y-axis with 95% CI bands](figures/cross_sequence_regional_profile.png)

| Metabolite | Spearman ρ | p-value | n roots |
|---|---:|---:|---:|
| GPCPCh | 0.93 | 2.1×10⁻³⁵ | 82 |
| CrPCr | 0.90 | 3.2×10⁻³¹ | 82 |
| NAANAAG | 0.89 | 5.0×10⁻²⁹ | 82 |
| Ins | 0.88 | 7.0×10⁻²⁸ | 82 |
| GluGln | 0.85 | 9.4×10⁻²⁴ | 82 |

### Interpretation

* **Regional profiles reproduce strongly across sites and sequences for
  every metabolite tested** (ρ = 0.85–0.93, all p < 10⁻²³). This is direct
  evidence that MRSIPrep's registration, parcellation, and regional-profile
  estimation preserve genuine spatial structure in the underlying
  metabolite maps across acquisitions that differ in essentially every
  technical respect except the processing pipeline itself — not just on
  the specific acquisition the pipeline was developed and tuned against.

* **LPN-Project and BioPsych-Project's absolute signal levels differ by
  roughly three orders of magnitude** (LPN-Project regional values in the
  hundreds-to-low-thousands; BioPsych-Project in the 0–2 range), uniform
  in direction and magnitude across all five metabolites. This is
  consistent with a scanner-, sequence-, or reconstruction-level scaling
  or referencing difference between the two acquisitions, not a
  biological effect or a pipeline artifact — a genuinely different
  absolute unit convention upstream of MRSIPrep, not something MRSIPrep
  itself introduces. The figure above plots each cohort on its own
  y-axis specifically to make the shared *pattern* visible despite this;
  the Spearman correlations are computed on each cohort's native scale,
  before that per-axis rescaling for display, and are unaffected by it
  (Spearman's rank correlation is scale- and offset-invariant by
  construction).

* **Practical consequence**: any secondary analysis that pools MRSIPrep
  regional outputs across these two cohorts directly — a group comparison
  or a connectivity analysis spanning both — would need an explicit
  harmonization or normalization step first, despite the underlying
  relative regional pattern being highly consistent. Reproducibility of
  pattern does not imply poolability of raw values.

* **GPCPCh has the strongest cross-cohort agreement (ρ = 0.93) and GluGln
  the weakest (ρ = 0.85)**, though the weakest is still a strong, highly
  significant correlation. This differentiation across metabolites is
  more informative than a single pooled "everything correlates" number
  would be, and is broadly consistent with GluGln's known greater
  sensitivity to sequence and TE choice relative to more robust
  metabolites like creatine-referenced signals.

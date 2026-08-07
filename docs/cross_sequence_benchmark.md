# Cross-Site/Cross-Sequence Regional Profile Reproducibility

The benchmarks on the other two pages validate MRSIPrep's registration and
detection performance on data it was built and tuned against — a real
3T/7T ECCENTRIC pair, and a synthetic ground-truth cohort. This page tests
something harder: whether MRSIPrep-derived regional metabolite profiles
reproduce on entirely independent real-world data — different subjects,
different scanners, different sites, and different MRSI sequences,
processed with the same pipeline and parcellation. Two independent
comparisons are reported, one at 3T and one at 7T.

Because absolute metabolite units are not expected to agree across
different sequences and field strengths — scanner-, sequence-, and
reconstruction-dependent scaling and referencing choices affect the
overall signal level independently of true tissue concentration — this is
deliberately framed as a test of whether the **relative spatial pattern**
of regional metabolite levels reproduces across acquisitions, not whether
absolute values agree.

## 3T: Lausanne3T-FID vs. Lausanne3T-ECCENTRIC

### Dataset

Two independently acquired real-world datasets, merged into one group-level
MRSIPrep connectivity/profile archive.

| | Lausanne3T-FID | Lausanne3T-ECCENTRIC |
|---|---|---|
| n | 12 | 15 |

### Method

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

### Results

| Metabolite | Spearman ρ | p-value | n roots |
|---|---:|---:|---:|
| GPCPCh | 0.93 | 2.1×10⁻³⁵ | 82 |
| CrPCr | 0.90 | 3.2×10⁻³¹ | 82 |
| NAANAAG | 0.89 | 5.0×10⁻²⁹ | 82 |
| Ins | 0.88 | 7.0×10⁻²⁸ | 82 |
| GluGln | 0.85 | 9.4×10⁻²⁴ | 82 |

## 7T: Vienna7T-FID vs. Geneva7T-ECCENTRIC

### Dataset

Two independently acquired 7T datasets, entirely disjoint from the 3T
comparison above — different sites, scanners, and MRSI sequences.

| | Vienna7T-FID | Geneva7T-ECCENTRIC |
|---|---|---|
| n | 5 | 26 |

Vienna7T-FID's quantification pipeline did not export a per-metabolite
CRLB map, so its regional profiles use MRSIPrep's CRLB-fallback path: a
metabolite with no CRLB map is treated as 0% uncertainty (no injected
noise) rather than excluded, collapsing the usual CRLB-perturbed Monte
Carlo draw to a single deterministic point estimate at the native MRSI
signal value. Geneva7T-ECCENTRIC's regional profiles use the standard
$K_{\mathrm{pert}}=50$ CRLB-perturbed estimation, reduced to a comparable
per-subject point estimate via the median across draws.

### Method

Same GM-only filtering and sub-parcel-merging procedure as the 3T
comparison above, applied to the 9 metabolites both datasets fit as
individually-resolved channels (CrPCr, GPCPCh, Ins, NAA, NAAG, Glu, Gln,
GABA, GSH — not combined into MRSIPrep's usual 5 aggregate channels,
since Vienna7T-FID's quantification never produced e.g. a joint NAA+NAAG
value). Brainstem sub-parcels (midbrain, pons, medulla, superior
cerebellar peduncle) are excluded as not cleanly gray matter, leaving 261
of 265 parcels, merged into 119 GM root regions.

### Results

![Cross-site/cross-sequence regional metabolic profile reproducibility at 3T and 7T. Panel A: Lausanne3T-FID vs. Lausanne3T-ECCENTRIC, 82 GM root regions, 5 metabolites, each dataset on its own y-axis with 95% CI bands. Panel B: Vienna7T-FID vs. Geneva7T-ECCENTRIC, 119 GM root regions, 9 metabolites, Spearman correlation per metabolite.](figures/cross_sequence_regional_profile_3t_7t.png)

| Metabolite | Spearman ρ | p-value | n roots |
|---|---:|---:|---:|
| Ins | 0.90 | 2.2×10⁻⁴⁴ | 119 |
| Glu | 0.90 | 1.7×10⁻⁴⁴ | 119 |
| CrPCr | 0.90 | 7.0×10⁻⁴³ | 119 |
| GPCPCh | 0.90 | 6.0×10⁻⁴³ | 119 |
| NAA | 0.88 | 1.9×10⁻⁴⁰ | 119 |
| NAAG | 0.82 | 9.3×10⁻³¹ | 119 |
| GABA | 0.81 | 6.8×10⁻²⁹ | 119 |
| GSH | 0.72 | 4.0×10⁻²⁰ | 119 |
| Gln | 0.68 | 1.6×10⁻¹⁷ | 119 |

Regional profiles reproduce strongly at both field strengths, across four
independent sites/sequences in total, with every metabolite reaching a
significant, positive Spearman correlation.

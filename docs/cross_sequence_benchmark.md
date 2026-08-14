# Cross-Site/Cross-Sequence Regional Profile Replicability

The benchmarks on the other two pages validate MRSIPrep's registration and
detection performance on data it was built and tuned against: a real
3T/7T ECCENTRIC pair, and a synthetic ground-truth cohort. Both are
reproducibility evidence, in the sense that the same pipeline and
configuration are applied to inputs it was developed against. This page
tests something harder, replicability: whether MRSIPrep-derived regional
metabolite profiles replicate on entirely independent real-world data:
different subjects, different scanners, different sites, and different
MRSI sequences, processed with the same pipeline and parcellation. Three
independent comparisons are reported: two at 3T, isolating in turn the
effect of sequence (same site, different sequence) and of site (different
site, same sequence), and one at 7T.

Because absolute metabolite units are not expected to agree across
different sequences and field strengths (scanner-, sequence-, and
reconstruction-dependent scaling and referencing choices affect the
overall signal level independently of true tissue concentration), this is
deliberately framed as a test of whether the **relative spatial pattern**
of regional metabolite levels replicates across acquisitions, not whether
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
each of the 82 regions of the `chimeraLFMIHIFIS` scale-1 parcellation:

1. **Per-subject point estimate**: the median across the
   $K_{\mathrm{pert}}=50$ CRLB-perturbed draws in the archive's
   `metab_profiles_subj_list` array (shape `(subjects, parcels, nperm,
   metabolites)`), MRSIPrep's uncertainty-propagated regional profile
   estimation, see the main docs' connectivity/profile documentation.
2. **GM-only filtering**: excludes only `brain-stem-midbrain` as not
   cleanly gray matter. This parcellation scheme contains no white matter
   parcels at all: cortex (`ctx-`), cerebellum (`cer-`), hippocampus
   (`hipp-`), subcortical nuclei (`subc-`), and thalamic nuclei (`thal-`)
   are all retained. A GM+WM follow-up is left for future work once a
   scheme with WM parcels is used.

   *Implementation note:* since only `chimeraLFMIHIFIS` scale-2 and
   scale-3 atlases are bundled, this scale-1 region set is obtained from
   the bundled scale-3 atlas (203 parcels) by averaging sub-parcels that
   share the same anatomical root and differ only by the Lausanne
   scheme's finer sub-parcellation index (e.g. `ctx-lh-superiorfrontal_1`
   through `_8` are the same gyrus at finer granularity, not eight
   distinct regions), which is equivalent to scale-1 granularity.
3. **Group profile**: for each metabolite and region, the mean (and
   95% CI, across subjects) within each cohort.
4. **Cross-cohort comparison**: Spearman correlation between the two
   cohorts' 82-region mean profiles, per metabolite, a threshold-
   independent, scale-free test of whether the two acquisitions rank
   regions the same way, deliberately insensitive to any absolute scale
   difference between them.
5. **Spatially-aware significance testing**: regions are not
   independent, exchangeable units: neighboring regions share spatial
   autocorrelation (biology, PVC/registration smoothing, GM gradients),
   which anti-conservatively inflates the significance of a plain
   parametric Spearman test. Because this parcellation spans cortex,
   subcortex, thalamus, cerebellum, and hippocampus rather than a single
   continuous cortical sheet, a classical spherical spin test does not
   apply; instead, p-values are computed against a null distribution of
   variogram-matched spatial surrogate maps (Burt et al. 2020,
   `brainsmash`), built from a Euclidean distance matrix between
   region centroids (from the bundled `chimera-LFMIHIFIS-1` atlas).
   For each metabolite, 5,000 surrogates are generated independently for
   each side of the comparison (preserving that side's own spatial
   autocorrelation while destroying its true correspondence with the
   other side); the reported p-value is the more conservative of the two
   resulting one-sided empirical tests.

### Results

| Metabolite | Spearman ρ | p-value | n roots |
|---|---:|---:|---:|
| GPCPCh | 0.93 | <2×10⁻⁴ | 82 |
| CrPCr | 0.90 | <2×10⁻⁴ | 82 |
| NAANAAG | 0.89 | <2×10⁻⁴ | 82 |
| Ins | 0.88 | <2×10⁻⁴ | 82 |
| GluGln | 0.85 | <2×10⁻⁴ | 82 |

p-values are empirical (5,000 surrogates per side); `<2×10⁻⁴` indicates
no surrogate in either direction ever matched or exceeded the observed
correlation, i.e. the true p-value is below the resolution of this many
surrogates, not exactly this value.

## 3T: Lausanne3T-FID vs. Geneva3T-FID

### Dataset

Two independently acquired real-world datasets using the **same**
Cartesian CS-SENSE sequence, on two independent 3T scanners at two
different sites, isolating the site/scanner effect from the sequence
effect tested above.

| | Lausanne3T-FID | Geneva3T-FID |
|---|---|---|
| n | 12 | 59 |

### Method

Identical to the Lausanne3T-FID vs. Lausanne3T-ECCENTRIC method above: 5
metabolites (CrPCr, GluGln, GPCPCh, NAANAAG, Ins), same 82-region
`chimeraLFMIHIFIS` scale-1 parcellation, same spatially-aware
significance testing.

### Results

| Metabolite | Spearman ρ | p-value | n roots |
|---|---:|---:|---:|
| GPCPCh | 0.83 | <2×10⁻⁴ | 82 |
| NAANAAG | 0.75 | <2×10⁻⁴ | 82 |
| CrPCr | 0.70 | <2×10⁻⁴ | 82 |
| Ins | 0.64 | <2×10⁻⁴ | 82 |
| GluGln | 0.63 | <2×10⁻⁴ | 82 |

p-values are empirical (5,000 surrogates per side, see the first 3T
Method above); `<2×10⁻⁴` indicates no surrogate in either direction ever
matched or exceeded the observed correlation.

Correlations here, while still strong and significant for every
metabolite, are consistently lower than Lausanne3T-FID vs.
Lausanne3T-ECCENTRIC's despite comparing the **same** sequence rather
than two different ones. This isolates a genuine site/scanner effect on
top of the sequence effect tested above: the first 3T comparison holds
the scanner fixed and varies the sequence, while this one holds the
sequence fixed and varies the scanner/site/subject population
(Geneva3T-FID is also the largest cohort compared on this page, n=59),
so the lower correlation here indicates that cross-site variability
(hardware, local protocol implementation, subject demographics)
contributes at least as much replicability-limiting variance as changing
the pulse sequence itself, on top of a shared processing pipeline.

![Cross-site regional metabolic profile replicability, Lausanne3T-FID vs. Geneva3T-FID, 82 GM regions, 5 metabolites, each dataset on its own y-axis with 95% CI bands.](figures/cross_sequence_regional_profile_geneva3t_supplementary.png)

## 7T: Vienna7T-FID vs. Geneva7T-ECCENTRIC

### Dataset

Two independently acquired 7T datasets, entirely disjoint from the 3T
comparison above: different sites, scanners, and MRSI sequences.

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

Same GM-only filtering, scale-1 parcellation, and spatially-aware
significance testing (variogram-matched surrogates against region
centroid distances, 5,000 surrogates per side) as the 3T comparisons
above, applied to the 9 metabolites both datasets fit as
individually-resolved channels (CrPCr, GPCPCh, Ins, NAA, NAAG, Glu, Gln,
GABA, GSH, not combined into MRSIPrep's usual 5 aggregate channels,
since Vienna7T-FID's quantification never produced e.g. a joint NAA+NAAG
value), on the same scale-1 parcellation restricted to 119 GM regions
(excluding brainstem sub-parcels: midbrain, pons, medulla, superior
cerebellar peduncle).

### Results

![Cross-site/cross-sequence regional metabolic profile replicability at 3T and 7T. Panel A: Lausanne3T-FID vs. Lausanne3T-ECCENTRIC, 82 GM regions, 5 metabolites, each dataset on its own y-axis with 95% CI bands. Panel B: Vienna7T-FID vs. Geneva7T-ECCENTRIC, 119 GM regions, 9 metabolites, Spearman correlation per metabolite.](figures/cross_sequence_regional_profile_3t_7t.png)

| Metabolite | Spearman ρ | p-value | n roots |
|---|---:|---:|---:|
| Ins | 0.90 | <2×10⁻⁴ | 119 |
| Glu | 0.90 | <2×10⁻⁴ | 119 |
| CrPCr | 0.90 | <2×10⁻⁴ | 119 |
| GPCPCh | 0.90 | <2×10⁻⁴ | 119 |
| NAA | 0.88 | <2×10⁻⁴ | 119 |
| NAAG | 0.82 | <2×10⁻⁴ | 119 |
| GABA | 0.81 | <2×10⁻⁴ | 119 |
| GSH | 0.72 | 6×10⁻⁴ | 119 |
| Gln | 0.68 | 1×10⁻³ | 119 |

p-values are empirical (5,000 surrogates per side, see the 3T Method
above); `<2×10⁻⁴` indicates no surrogate in either direction ever
matched or exceeded the observed correlation.

Regional profiles replicate strongly across all three comparisons, with
every metabolite reaching a significant, positive Spearman correlation
under a spatially-aware null model that accounts for the
non-independence of neighboring brain regions. Combined, the three
comparisons span three independent sites, five acquisitions, and two
field strengths.

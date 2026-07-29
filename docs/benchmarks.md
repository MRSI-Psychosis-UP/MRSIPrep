# Runtime Benchmarks

Wall-clock timing for MRSIPrep's `mni-norm` mode (default settings, ANTs
registration backend) across a range of `--nthreads` values, on two
subjects acquired at different field strengths, to give a sense of how
runtime scales with acquisition resolution as well as thread count.

## Hardware

### Compute (this benchmark)

| Component | Spec |
|---|---|
| CPU | Intel Core i9-14900K, 24 cores / 32 threads, up to 6.0 GHz |
| RAM | 125 GB |
| GPU | NVIDIA RTX 5000 Ada Generation, 32 GB VRAM (not used by `mni-norm` mode; SynthSeg here ran CPU-only) |
| OS | Linux 5.15 (Ubuntu) |
| Docker | 29.4.1 |
| MRSIPrep image | `mrsiup/mrsiprep:cpu` |

### MRI scanners

| | 3 Tesla | 7 Tesla |
|---|---|---|
| Scanner | Magnetom TrioTim | Magnetom Terra.X |
| Coil | 32-channel | 32-channel |

## MRSI Acquisition: ECCENTRIC

Both datasets were acquired with the **ECCENTRIC** FID-MRSI sequence
([Klauser et al., 2024, *Imaging Neuroscience*](https://direct.mit.edu/imag/article/doi/10.1162/imag_a_00313/124597/ECCENTRIC-A-fast-and-unrestrained-approach-for),
"ECCENTRIC: A fast and unrestrained approach for high-resolution
whole-brain metabolic imaging at ultra-high magnetic field"), a
compressed-sensing-accelerated concentric-ring k-space trajectory
designed for fast, high-resolution whole-brain MRSI.

### Metabolite acquisition

| Parameter | 3 Tesla | 7 Tesla |
|---|---|---|
| Field of view | 220 × 220 × 130 mm³ | 220 × 220 × 110 mm³ |
| Slab thickness | 95 mm | 100 mm |
| Nominal voxel size | 5.0 × 5.0 × 5.2 mm³ | 3.4 × 3.4 × 3.5 mm³ |
| Scan resolution | 44 × 44 × 25 | 64 × 64 × 31 |
| TR | 457 ms | 400 ms |
| TE₁ / TE₂ | 0.78 ms / 65 ms | 0.68 ms |
| Flip angle | 45° | 35° |
| Spectral bandwidth | 1320 Hz | 2280 Hz |
| Vector size | 512 points | 688 FID points |
| Spatial encoding | ECCENTRIC trajectory, circle radius 0.25 k_max | ECCENTRIC trajectory, circle radius 0.25 k_max |
| Acceleration factor | 2.5 | 2.5 |
| Total acquisition time | 6 min 54 s | 11 min 52 s |

### Water reference

Matched spatial coverage, lower resolution — used for coil combination,
field correction, and metabolite intensity normalization.

| Parameter | 3 Tesla | 7 Tesla |
|---|---|---|
| Field of view | 220 × 220 × 130 mm³ | 220 × 220 × 110 mm³ |
| Nominal voxel size / resolution | 10.0 × 10.0 × 10.0 mm³ | 10 × 10 × 10 mm³ |
| Scan resolution | 22 × 22 × 13 | — |
| TR | 460 ms | 404 ms |
| TE₁ / TE₂ | 0.72 ms / 65 ms | 0.59 ms |
| Flip angle | 45° | 35° |
| Acquisition time | 1 min 21 s | 59 s |

### Reconstruction and quantification

Both MRSI acquisitions were reconstructed using a compressed-sensing SENSE
low-rank framework with total-generalized-variation regularization and
simultaneous lipid suppression. Metabolite quantification was performed
with **LCModel**.

## MRSIPrep Benchmark Method

Two single-subject `mrsiprep` runs, one per dataset, repeated at
`--nthreads` 8, 12, 16, and 32 (`--nproc 1` throughout — one subject per
run, so `--nthreads` is the only varying parameter). Each run used a
**fresh `--work-dir`** (no Nipype caching carried over between
thread-count variants), so every number below reflects genuine
full-pipeline computation, not a partially cached rerun. All 8 runs (2
subjects × 4 thread counts) were executed **strictly sequentially, one at
a time**, with no other run or concurrent load on the machine, to rule
out cross-run resource contention affecting the timings.

- **3 Tesla subject** — a real MRSI acquisition with an MP2RAGE anatomical.
- **7 Tesla subject** — a real MRSI acquisition with an MP2RAGE
  anatomical.

Both runs: `--mode mni-norm --metabolites NAANAAG,GPCPCh,CrPCr,GluGln,Ins
--ref-met CrPCr`, default `--synthseg-mode robust`, default ANTs
registration backend.

### Resolution and useful-voxel counts

The two subjects differ substantially in both anatomical (T1w) and MRSI
grid resolution — this is the main driver of the runtime difference below,
since ANTs registration and SynthSeg both operate on the full-resolution
T1w volume, not the coarser MRSI grid.

| | 3 Tesla | 7 Tesla | Ratio (7T / 3T) |
|---|---:|---:|---:|
| T1w voxel size (mm) | 1.00 × 1.33 × 1.33 | 0.66 × 0.60 × 0.60 | — |
| T1w volume shape | 160 × 192 × 192 | 256 × 396 × 416 | — |
| T1w total voxels | ~5.9 M | ~42.2 M | **~7.2×** |
| MRSI voxel size (mm) | 5.00 × 5.00 × 5.25 | 3.44 × 3.44 × 3.55 | — |
| MRSI useful (non-zero, in-brain) voxels | 15,315 | 32,638 | **~2.1×** |

## Results

![MRSIPrep runtime by pipeline step and --nthreads, 3 Tesla vs 7 Tesla](figures/benchmark_nthreads.png)

Stacked bar height = total wall-clock elapsed time (label above each bar);
segments show each pipeline step's share. "Container startup / other
overhead" covers Docker startup and the CLI's own preflight input-check,
which aren't wrapped in a named, timed pipeline step.

## Interpretation

* **Runtime is essentially flat from 8 to 32 threads** for both subjects when each run is isolated from other load: 3T ranges 300–318s (~6% spread) and 7T ranges 1227–1235s (under 1% spread), with no consistent downward trend past 8 threads. ANTs registration (the largest single segment at both field strengths) and SynthSeg tissue segmentation show effectively no benefit from more than ~8 threads, so for batch processing it is generally better to use ~8 threads per subject and increase `--nproc` (running more subjects in parallel) rather than allocate more threads to each individual subject.

* **The 7T subject takes about 4× longer than the 3T subject** (~20.5 vs. ~5.1 minutes). This is mainly due to the 7T T1w image having ~7.2× more voxels, which increases registration and segmentation costs. The MRSI grid has only ~2.1× more usable voxels, making anatomical — not MRSI — resolution the main runtime driver. Tissue segmentation (`mri_synthseg`) and MRSI-T1w-MNI registration (ANTs rigid+affine+SyN) together account for the large majority of total runtime at both field strengths.

## Registration Frameworks

`--registration-backend` offers **ANTs** (default: rigid+SyN for
MRSI→T1w, rigid+affine+SyN for T1w→MNI — see the transform-stage table
below, since the two ANTs stages are not symmetric) and **FSL** (FLIRT
affine, with an FNIRT deformable stage on by default —
`--no-fsl-deformable` for FLIRT-only). This section compares four
MRSI→T1w registration configurations — **ANTs (Rigid+SyN)**, **ANTs
(Rigid+Affine)**, **FSL FLIRT-only**, and **FSL FLIRT+FNIRT** — each
against both supported T1w registration targets, **brain**
(skull-stripped) and **brain+CSF** (skull-stripped T1w with the CSF
compartment re-added, since CSF also produces real MRSI signal that a
brain-only target would otherwise clip at the boundary).

**Transform used at each registration stage, by backend:**

| Backend | MRSI → T1w | T1w → MNI |
|---|---|---|
| ANTs (Rigid+SyN) — mrsiprep's default | Rigid + SyN (deformable) — **no separate Affine stage**, `antsRegistrationSyN[sr]` | Rigid + Affine + SyN (deformable), `antsRegistrationSyN[s]` |
| ANTs (Rigid+Affine) | Rigid + Affine — a genuine second registration run (`antsRegistration`, `transform="a"`), since mrsiprep's default MRSI→T1w stage never computes an Affine stage to reuse | Rigid + Affine (the SyN warp dropped from the default `[s]` run above — this stage already has a real Affine, so no extra registration needed here) |
| FSL FLIRT-only | Affine only (FLIRT, 12 DOF, `corratio` cost) | Affine only (FLIRT, 12 DOF) |
| FSL FLIRT+FNIRT | Affine (FLIRT) + deformable warp (FNIRT, `--fsl-deformable`) | Affine only (FLIRT, 12 DOF) — FNIRT is not used for this stage |

Note that `--fsl-deformable` only adds a deformable (FNIRT) stage to the
**MRSI→T1w** registration; the **T1w→MNI** stage is always FLIRT affine-only
under the FSL backend, in both the FLIRT-only and FLIRT+FNIRT variants
compared here.

**The two ANTs stages are asymmetric, which is why "ANTs (Rigid+Affine)"
needed a real second registration run, not just a transform dropped from
the default pipeline.** ANTs' default MRSI→T1w stage
(`antsRegistrationSyN[sr]`) runs a Rigid stage followed directly by SyN —
`antsRegistrationSyN.sh`'s own `sr` code has no separate Affine stage at
all (MRSI and T1w start from roughly the same subject geometry, so
mrsiprep's default skips the extra affine correction there). Dropping
SyN from that default leaves Rigid-only, not Rigid+Affine. **ANTs
(Rigid+Affine)** in this comparison therefore required actually running
`antsRegistration` with `transform="a"` at the MRSI→T1w stage — genuine
new registration compute, not a reuse of an already-computed transform.
ANTs' T1w→MNI stage (`antsRegistrationSyN[s]`) already runs the full
three-stage Rigid → Affine → SyN pipeline by default, since subject
anatomy genuinely differs from the MNI template in scale and shape, not
just position — for that stage, `antsRegistration` always writes each
linear stage's transform to its own independent file, so the
already-computed Rigid+Affine transform is reused directly with the SyN
warp simply dropped, no recompute needed there.

### Method

Full `mrsiprep --mode mni-norm` runs (not isolated registration calls) on
the same 3 Tesla and 7 Tesla subjects used above, varying
`--registration-backend`/`--fsl-deformable` and
`--registration-t1-target` (6 combinations × 2 subjects = 12 runs). See
`experiments/registration_backend_benchmark.py` (not published; internal
validation script). **ANTs (Rigid+Affine)** is added on top of this: the
MRSI→T1w stage is a genuine new `antsRegistration transform="a"` run (2
subjects × 2 targets = 4 registrations, timed directly), while the
T1w→MNI stage reuses the already-computed Rigid+Affine transform from
the default **ANTs (Rigid+SyN)** run (SyN warp dropped, no recompute) —
so this configuration is partly new compute, partly reused, unlike the
VBA benchmark's equivalent comparison where both stages could be reused
directly (see the note there on why the two benchmarks differ in this
respect).

Leakage is reported as **signal-weighted mass outside the brain mask**:
at each quality-passing voxel (resampled CRLB ≤ 20, mrsiprep's own default
`--crlb-max`) the resampled CrPCr signal magnitude is summed; the
percentage reported is the fraction of that total signal mass that falls
outside the reference brain mask. This is deliberately **not** a raw
voxel count of "covered" voxels outside the mask — a boundary voxel
carrying negligible signal and a voxel carrying real, substantial signal
in the wrong location both count as "1 voxel" under a voxel-count metric,
which conflates thin resampling/registration boundary artifacts with
genuine misregistration. Weighting by signal magnitude fixes that: a
one-voxel-thick sliver of near-zero smeared or dilated boundary
contributes almost nothing to the percentage, while real signal
displaced into clearly wrong anatomy does. (Two earlier, superseded
versions of this metric were tried and rejected: "resampled signal
nonzero" as the coverage criterion overstated leakage via linear/spline
interpolation smear at the boundary; a corrected mask-based voxel-count
metric fixed that but then over-penalized FNIRT specifically, because
nearest-neighbor-resampling a **binary** mask through FNIRT's nonlinear
warp locally dilates the mask's footprint independent of true
registration accuracy. Weighting by actual signal magnitude avoids both
problems at once.)

This is computed against three reference masks: the T1w brain-only mask,
the T1w brain+CSF mask, and the MNI152 template's own standard brain mask
(in MNI space) — summing how much "covered" signal mass falls **outside**
each reference mask.

### Results

**3 Tesla subject**, all four backends × both targets, axial slice, same
intensity scale throughout:

![CrPCr resampled to MNI space, overlaid on the full-head MNI152 template, 3 Tesla subject, 2 columns (brain / brain+CSF) x 4 rows (ANTs Rigid+SyN / ANTs Rigid+Affine / FLIRT / FLIRT+FNIRT)](figures/registration_backend_mni_overlay_3t.png)

**7 Tesla subject**, same layout and intensity-scale convention (its own
scale, since 7T signal levels differ from 3T):

![CrPCr resampled to MNI space, overlaid on the full-head MNI152 template, 7 Tesla subject, 2 columns (brain / brain+CSF) x 4 rows (ANTs Rigid+SyN / ANTs Rigid+Affine / FLIRT / FLIRT+FNIRT)](figures/registration_backend_mni_overlay_7t.png)

The full-head (non-skull-stripped) MNI152 template makes the skull
boundary visible as a bright ring; voxels with values below 0.1 are
rendered transparent so the underlying template stays visible through
low-signal regions. Signal extending past the skull ring, or with a
jagged/scalloped rather than smooth outer edge, indicates voxels that have
leaked beyond the true brain boundary during registration — visible here
for both FSL variants and, most noticeably, for ANTs (Rigid+Affine) at
both field strengths, which shows the coarsest, most scalloped outer edge
of any of the four configurations.

**Signal-weighted MNI-space leakage, by backend** (brain target;
brain+CSF is within ±0.3 points of these and shows the same pattern):

![Bar chart: percentage of resampled CrPCr signal mass outside the MNI152 brain mask, by registration backend, faceted by 3 Tesla vs 7 Tesla](figures/registration_backend_mni_outside_comparison.png)

**Total `mni-norm` wall-clock runtime, by backend** (same two subjects,
averaged across the `brain`/`brain+CSF` targets) — **ANTs (Rigid+Affine)**
is not a full `mni-norm` run (see Method above), so it isn't a
like-for-like total-pipeline number; instead its bar reports the
**registration-only** wall-clock time (both stages combined, timed
directly via `mrsiprep.interfaces.ants.register()`, `nthreads=16`
matching the other runs' default), which should be read as a lower bound
on how much a full `mni-norm` run would take, not a directly comparable
total:

![Bar chart: total mni-norm runtime in minutes, by registration backend (ANTs Rigid+SyN, ANTs Rigid+Affine, FSL FLIRT, FSL FLIRT+FNIRT), for 3 Tesla vs 7 Tesla](figures/registration_backend_runtime.png)

### Interpretation

* **ANTs (Rigid+SyN), mrsiprep's default, has the least signal-weighted
  leakage at both field strengths** (0.34% at 3T, 0.44% at 7T) — roughly
  6-10× less than FSL FLIRT-only (2.1%, 0.97%) and 12-16× less than FSL
  FLIRT+FNIRT (5.4%, 2.7%). Unlike the raw voxel-count metric, this
  ranking agrees with the overlay figures' visual impression of ANTs
  (Rigid+SyN) producing the sharpest, most anatomically detailed result.
  In absolute terms all backends leak well under 6% of total signal
  mass, so none is catastrophically wrong — but the relative gap between
  backends is real and consistent across both subjects.

* **ANTs (Rigid+Affine) is, surprisingly, the second-leakiest of all
  four configurations — worse than either FSL variant at 7T.** It leaks
  4.30% of signal mass at 3T and 4.73% at 7T: roughly 12× more than the
  default ANTs (Rigid+SyN) pipeline at 3T and roughly 11× more at 7T,
  worse than FSL FLIRT-only at both field strengths (2.1%, 0.97%), and
  at 7T even worse than FSL FLIRT+FNIRT (4.73% vs. 2.73%). This is a
  genuinely unexpected result: adding a real affine correction on top of
  rigid alignment at the MRSI→T1w stage did not reduce leakage relative
  to rigid-only, it *increased* it. A plausible explanation is that the
  affine stage's extra degrees of freedom (scale, shear) are being fit
  to noise or local signal structure in the relatively low-resolution,
  low-contrast MRSI reference image without a deformable stage
  afterward to correct any resulting distortion — since ANTs' own
  default pipeline never uses affine at this stage without immediately
  following it with SyN, this backend combination is untested territory
  for mrsiprep's own default configuration, and this result is a data
  point against introducing it as an option without further
  investigation, not a recommendation for it.

* **This mirrors the direction (if not the exact numbers) of the VBA
  Detection Benchmark's finding that ANTs' rigid+affine configuration
  there performed at least as well as, and sometimes better than, the
  full SyN pipeline for focal-signal detection** (see the [Voxel-Based
  Detection Benchmark](vba_benchmark.md)) — but the two benchmarks are
  not directly comparable: the VBA benchmark's "no SyN" comparison reused
  mrsiprep's actual default transforms with SyN dropped (Rigid-only at
  MRSI→T1w, since that is what mrsiprep's default pipeline already
  computes there), while this benchmark's ANTs (Rigid+Affine) required a
  genuinely different, non-default MRSI→T1w registration (a real Affine
  stage that mrsiprep's own default pipeline never runs at that stage).
  The two results are not in tension with each other; they are testing
  different registration configurations under different tasks, and
  should not be read as contradicting one another.

* **FSL FLIRT+FNIRT leaks more signal mass than FLIRT-only, at both field
  strengths** (5.4% vs. 2.1% at 3T; 2.7% vs. 0.97% at 7T) — i.e. adding
  the deformable stage does not reduce real signal leakage relative to
  the affine-only baseline in this metric, even though it did appear to
  reduce the raw voxel-count leakage percentage at 7T under the earlier,
  superseded mask-based metric. That earlier result was the mask-dilation
  artifact described above; once leakage is weighted by actual signal
  magnitude rather than counting dilated boundary voxels, FNIRT is
  leakier than FLIRT-only, though less leaky than ANTs (Rigid+Affine) at
  either field strength.

* **Registration-only runtime for ANTs (Rigid+Affine) is well under a
  minute at either field strength** (0.28 min at 3T, 0.73 min at 7T —
  see the note above on why this isn't a like-for-like full-pipeline
  comparison), far faster than any of the full `mni-norm` runs. But
  given its leakage result above, this speed is not a useful tradeoff on
  its own — a fast registration that leaks more signal than either FSL
  variant is not obviously preferable to FSL FLIRT-only (3.1-11.2 min,
  2.1%/0.97% leakage) purely on a speed/accuracy basis. **FNIRT's extra
  runtime cost is not paying for reduced leakage either:** at 3T, FNIRT
  (11.6 min) costs roughly 3.8× FLIRT-only (3.1 min) and is comparable
  to ANTs (Rigid+SyN) (9.3 min); at 7T the gap widens sharply — FNIRT
  (53.0 min) is roughly 4.7× FLIRT-only (11.2 min) and nearly 2× ANTs
  (Rigid+SyN) itself (27.0 min), making it the slowest of the three
  full-pipeline options despite also having higher leakage than either
  ANTs (Rigid+SyN) or FSL FLIRT-only. There is no longer a clear case
  for `--fsl-deformable` over FLIRT-only purely on these two metrics;
  ANTs (Rigid+SyN) remains the best combination of accuracy and runtime
  among the full-pipeline options, and `--no-fsl-deformable` is a
  reasonable choice for FSL users who want to avoid FNIRT's runtime cost
  without a leakage penalty.

* **Brain vs. brain+CSF as the T1w registration target has a small effect
  that flips direction between field strengths.** At 3T, brain+CSF is
  very slightly better than brain-only for every backend (by ≤0.02
  percentage points of signal mass). At 7T, brain+CSF is consistently
  *worse* than brain-only for every backend (by 0.1–0.5 percentage
  points) — the opposite of what higher spatial resolution alone would
  predict (more voxels landing purely in CSF should, in principle, make a
  CSF-inclusive target relatively more helpful, not less, at finer
  resolution). The effect is small in both directions relative to the
  gaps between backends, and its sign reverses between the two subjects
  here, so it should not be read as a reliable advantage for either
  target — the registration backend and deformable stage are the
  dominant factors, not the brain-vs-brain+CSF choice.

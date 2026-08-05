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
just position.

### Method

Full `mrsiprep --mode mni-norm` runs (not isolated registration calls) on
the same 3 Tesla and 7 Tesla subjects used above, varying
`--registration-backend`/`--fsl-deformable` and
`--registration-t1-target` (6 combinations × 2 subjects = 12 runs). 


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

Signal extending past the skull ring, or with a
jagged/scalloped rather than smooth outer edge, indicates voxels that have
leaked beyond the true brain boundary during registration — visible here
for both FSL variants and, most noticeably, for ANTs (Rigid+Affine) at
both field strengths, which shows the coarsest, most scalloped outer edge
of any of the four configurations.

**Signal-weighted MNI-space leakage and total `mni-norm` wall-clock
runtime, by backend** (brain target; brain+CSF leakage is within ±0.3
points of these and shows the same pattern, not shown). Runtime is
averaged across the `brain`/`brain+CSF` targets — **ANTs (Rigid+Affine)**
is not a full `mni-norm` run (see Method above), so it isn't a
like-for-like total-pipeline number; instead its bar reports the
**registration-only** wall-clock time (both stages combined, timed
directly via `mrsiprep.interfaces.ants.register()`, `nthreads=16`
matching the other runs' default, hatched in the figure), which should be
read as a lower bound on how much a full `mni-norm` run would take, not a
directly comparable total:

![Two-panel bar chart: (left) percentage of resampled CrPCr signal mass outside the MNI152 brain mask, by registration backend, faceted by 3 Tesla vs 7 Tesla; (right) total mni-norm runtime in minutes, by registration backend (ANTs Rigid+SyN, ANTs Rigid+Affine, FSL FLIRT, FSL FLIRT+FNIRT), for 3 Tesla vs 7 Tesla](figures/registration_backend_leakage_runtime.png)

### Conclusions
* **ANTs (Rigid+SyN), the mrsiprep default, produced the lowest signal-weighted leakage** at both 3T and 7T (0.34% and 0.44%), clearly outperforming FSL FLIRT-only (2.1% and 0.97%) and FLIRT+FNIRT (5.4% and 2.7%). This agrees with the visual overlays, where ANTs yielded the sharpest anatomical alignment.

* **ANTs (Rigid+Affine) performed unexpectedly poorly**, with 4.30% leakage at 3T and 4.73% at 7T. Its additional affine degrees of freedom may overfit the low-resolution MRSI reference when not followed by a deformable SyN stage. This non-default configuration therefore cannot currently be recommended.

* **Adding FNIRT to FLIRT increased both leakage and runtime.** At 7T, FNIRT required 53.0 minutes, compared with 11.2 minutes for FLIRT-only and 27.0 minutes for ANTs (Rigid+SyN). Overall, ANTs (Rigid+SyN) provides the best accuracy–runtime balance. For FSL users, FLIRT-only is preferable to FLIRT+FNIRT based on these results.

* **The choice between brain-only and brain+CSF registration targets had only a minor and inconsistent effect** across field strengths, indicating that the registration backend is the dominant factor.


# Runtime Benchmarks

Wall-clock timing for MRSIPrep's `mni-norm` mode (default settings, ANTs
registration backend) across a range of `--nthreads` values, on two
subjects acquired at different field strengths, to give a sense of how
runtime scales with acquisition resolution as well as thread count.

## Hardware

| Component | Spec |
|---|---|
| CPU | Intel Core i9-14900K, 24 cores / 32 threads, up to 6.0 GHz |
| RAM | 125 GB |
| GPU | NVIDIA RTX 5000 Ada Generation, 32 GB VRAM (not used by `mni-norm` mode; SynthSeg here ran CPU-only) |
| OS | Linux 5.15 (Ubuntu) |
| Docker | 29.4.1 |
| MRSIPrep image | `mrsiup/mrsiprep:cpu` |

## Method

Two single-subject runs, one per dataset, repeated at `--nthreads` 8, 12,
16, and 32 (`--nproc 1` throughout — one subject per run, so `--nthreads`
is the only varying parameter). Each run used a **fresh `--work-dir`**
(no Nipype caching carried over between thread-count variants), so every
number below reflects genuine full-pipeline computation, not a partially
cached rerun.

- **3 Tesla subject** — a synthetic MRSI signal on a real T1w anatomy (from
  the public [Test Dataset](index.md#test-dataset)).
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

### 3 Tesla subject

| `--nthreads` | Tissue seg. | MRSI preproc. | MRSI-T1w-MNI reg. | Tissue prob. maps | PVC | Resampling | SynthSeg QC | Regional extraction | **Total** |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8  | 72.7s | 2.3s | 194.8s | 0.7s | 0.2s | 11.4s | 9.5s | 0.8s | **309.7s** |
| 12 | 72.0s | 2.3s | 196.4s | 0.7s | 0.2s | 11.2s | 9.4s | 0.7s | **310.2s** |
| 16 | 69.8s | 2.3s | 194.1s | 0.7s | 0.2s | 11.2s | 9.3s | 0.7s | **305.5s** |
| 32 | 65.6s | 2.3s | 195.1s | 0.7s | 0.2s | 11.4s | 9.6s | 0.7s | **303.1s** |

### 7 Tesla subject

| `--nthreads` | Tissue seg. | MRSI preproc. | MRSI-T1w-MNI reg. | Tissue prob. maps | PVC | Resampling | SynthSeg QC | Regional extraction | **Total** |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8  | 475.9s | 15.2s | 662.5s | 4.6s | 0.2s | 24.6s | 40.7s | 1.6s | **1245.1s** (20m45s) |
| 12 | 472.1s | 15.1s | 661.0s | 4.6s | 0.2s | 24.5s | 39.7s | 1.5s | **1237.9s** (20m38s) |
| 16 | 467.0s | 14.6s | 662.6s | 4.6s | 0.3s | 24.3s | 37.9s | 1.5s | **1232.0s** (20m32s) |
| 32 | 465.8s | 14.8s | 666.3s | 4.6s | 0.2s | 30.7s | 45.6s | 1.6s | **1251.0s** (20m51s) |

(`Anatomical preparation`, `Connectivity`, and `Reports` steps were all
≤0.02s in every run and are omitted from the table.)

## Interpretation

- **Total wall-clock time is essentially flat across `--nthreads` 8→32**
  for both subjects (variation is within ~2%, i.e. measurement noise, not
  a real trend). The two steps that dominate runtime — MRSI-T1w-MNI
  registration (ANTs) and SynthSeg tissue segmentation — do not scale
  meaningfully past roughly 8 threads on this hardware/dataset size. If
  you are choosing `--nthreads` for a batch of parallel subjects
  (`--nproc N`), there is little benefit to requesting more than ~8-12
  threads per subject process; it's more effective to increase `--nproc`
  (more subjects at once) than `--nthreads` per subject, once you're past
  that point.
- **7 Tesla data takes roughly 4x longer than the 3 Tesla subject**
  (~20.5 minutes vs. ~5.1 minutes). The T1w volume alone has **~7.2x**
  more voxels at 7T (higher-resolution MP2RAGE), which directly explains
  most of the registration and tissue-segmentation cost, since both
  operate on the full anatomical volume; the MRSI grid itself only has
  ~2.1x more useful voxels, so the anatomical resolution — not the MRSI
  resolution — is the dominant cost driver here.
- These numbers are for **`mni-norm` mode** only; `parc-con` mode adds
  SynthSeg+FAST tissue maps, PETPVC, and Chimera/MNI-atlas parcellation on
  top, and (if using Chimera's FreeSurfer `recon-all` dependency) is
  substantially slower — expect on the order of 1-3+ hours per subject,
  not reflected in this benchmark.

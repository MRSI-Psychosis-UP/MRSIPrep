# SynthSeg + FAST Tissue Backend Context

SynthSeg + FAST replaced the experimental CAT12-like Python port as the
preferred tissue segmentation path.

## Rationale

The CAT12 replication work did not reach acceptable CSF agreement. Even when
seeded with CAT12 p0/p1/p2/p3, the Python AMAP/cleanup path topped out below
the desired CSF Dice range. SynthSeg handled interior and exterior CSF,
including ventricular CSF, more reliably. FAST then provided partial-volume
GM/WM/CSF maps from the original T1 intensities.

## Current Backend

Backend name:

```text
synthseg-fast
```

High-level steps:

1. Run `mri_synthseg --parc` on the raw T1 using the selected fast, standard,
   or robust mode.
2. Resample SynthSeg labels to the raw T1 grid with nearest-neighbor
   interpolation using `nibabel.processing.resample_from_to`.
3. Build the extraction and FAST mask directly from the nonzero SynthSeg
   anatomical labels. Ventricular labels retained by default are:

```text
4   left lateral ventricle
5   left inferior lateral ventricle
14  third ventricle
15  fourth ventricle
43  right lateral ventricle
44  right inferior lateral ventricle
```

4. Exclude label `24` extra-ventricular CSF by default. Include it only when
   `--synthseg-include-outer-csf` is requested.
5. Build the masked T1 in Python:

```text
raw T1 * selected SynthSeg label mask
```

6. Use the masked T1 and mask as the MRSI-to-T1 registration target.
7. In parc-con mode, run FSL FAST on the masked T1.
8. Zero all GM/WM/CSF probabilities where the native-space SynthSeg label is
   `0`.
9. Correct small GM/WM leakage into the SynthSeg exterior CSF layer: where
   SynthSeg label `24` overlaps FAST GM or WM probability `> 0.01`, set GM
   and WM to `0` and CSF to `1`.
10. Export FAST partial-volume maps as:

```text
p1 = GM = FAST pve_1
p2 = WM = FAST pve_2
p3 = CSF = FAST pve_0
```

## Manual Validation Result

The SynthSeg extraction + FAST run produced better CSF maps than the CAT12-like
implementation. The Atropos equivalent was also tested and had improved CSF
relative to the CAT12-like path, but FAST remained the better choice for
partial-volume maps.

## Retired Code

The experimental CAT12-like Python port and vendored CAT12 AMAP/template assets
were removed. The `existing` backend still supports consuming precomputed
CAT12-style p1/p2/p3 maps from `derivatives/cat12` for compatibility.

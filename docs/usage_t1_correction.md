# T1 Saturation Correction

Raw fitted metabolite amplitudes are systematically underestimated when the
acquisition's TR is short relative to a metabolite's own T1 relaxation time,
since the spin system has not fully relaxed between excitations. MRSIPrep
does **not** correct for this by default (`--t1-correction none`) -- opt in
explicitly with `--t1-correction literature` to apply a single scalar
correction factor per metabolite, derived from the standard spoiled-FID
steady-state signal equation:

```
S/S0 = sin(alpha) * (1 - exp(-TR/T1)) / (1 - cos(alpha) * exp(-TR/T1))
```

using the acquisition's TR and nominal flip angle (read from a
dataset-level `mrsinmrs.json`, see [MRSinMRS](https://doi.org/10.1002/nbm.4484))
and a curated literature T1 value per metabolite per field strength
(`mrsiprep/config/t1_literature.json`). This is a **protocol-level** correction --
one factor per metabolite per recording, not per-voxel.

`--t1-correction voxelwise` instead applies a **per-voxel** correction
factor per metabolite, using a measured flip-angle (B1+) map in place of
the nominal flip angle -- TR and the literature T1 value remain scalar
(resonance-resolved T1 is not supported in either mode). This requires the
input layout to actually provide a flip-angle map
(`desc-b1map`, same grid as the metabolite maps); there is no fallback to
the nominal flip angle, and the step fails loudly if the map is absent.
A voxel where the measured flip angle yields a non-physical correction
factor (e.g. a near-zero flip angle outside the imaged object) is left
uncorrected rather than failing the whole recording; the fraction of such
voxels is recorded per metabolite in the confound table below.

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --metabolites CrPCr,GPCPCh,NAANAAG \
  --ref-met CrPCr \
  --parcellation-mode chimera \
  --t1-correction literature \
  --t1-correction-water-status unknown \
  --nthreads 16
```

## Requirements

Both `--t1-correction literature` and `--t1-correction voxelwise` require
a `mrsinmrs.json` at the BIDS root with unambiguous TR, flip angle, and
field-strength entries (under `CommonMetadata` or a matching `Recordings`
entry) -- the nominal `FlipAngle` is still read in `voxelwise` mode even
though it is not used for the correction itself, since it remains useful
provenance to compare against the measured B1+ map. Fails loudly,
per-recording, if metadata is missing or if two recognized spellings of
the same field disagree -- other recordings in a batch still process
normally. Since MRSinMRS defines no enforced schema, only a small
whitelist of key spellings is recognized (below); values are also
sanity-checked to be in a plausible range (e.g. TR must be in seconds,
not milliseconds). `--t1-correction voxelwise` additionally requires a
flip-angle (B1+) map discoverable as `desc-b1map` in the MRSI input
layout, on the same grid as the metabolite maps.

### Recognized `mrsinmrs.json` keys

Only these three keys are ever read by mrsiprep. Use the **canonical**
spelling for any new `mrsinmrs.json` -- the alternates are accepted for
compatibility with sidecars written elsewhere, but mixing spellings with
different values for the same field is treated as an error, not resolved
by preference order.

| Field | Canonical key | Accepted alternates | Units | Required for |
|---|---|---|---|---|
| Repetition time | `RepetitionTime` | `TR` | seconds | `--t1-correction literature` |
| Excitation flip angle | `FlipAngle` | `ExcitationFlipAngle` | degrees | `--t1-correction literature` |
| Field strength | `MagneticFieldStrength` | `FieldStrength` | Tesla | `--t1-correction literature` |

No other key is read programmatically by mrsiprep -- every other
`mrsinmrs.json` field (echo time, coil, sequence name, matrix size, water
suppression method, etc.) is accepted and stored for the QC report's
free-form MRSinMRS section (\S below), but has no effect on processing.
Field strength should be written as a bare number in Tesla (`7`, not
`"7T"`); TR must be in seconds (`0.45`, not `450` -- a value outside
0.05-20 is rejected as an implausible unit mismatch).

## Currently supported metabolites

Only metabolites with an exact entry in `mrsiprep/config/t1_literature.json`
and a non-null `t1_s` are supported. There is no fallback to a
similarly-named metabolite (e.g. requesting correction for `tNAA` will not
silently reuse `NAANAAG`'s T1). Entries with `status: "todo"` document known
gaps and raise a clear error rather than guessing.

| Metabolite | 3T T1 (s) | 7T T1 (s) | Status |
|---|---|---|---|
| CrPCr | 1.38 ± 0.13 SD | 1.78 ± 0.23 SD | verified |
| GABA | 1.31 ± 0.16 SD | 1.18 ± 0.42 SD | verified |
| GPCPCh | 1.06 ± 0.11 SD | 1.24 ± 0.21 SD | verified |
| GSH | 0.397 ± 0.044 SD | 1.06 ± 0.06 SD | verified |
| Gln | todo | 1.74 ± 0.23 SD | verified at 7T |
| Glu | 1.17 ± 0.08 SE | 1.75 ± 0.04 SD | verified |
| GluGln | 0.96 ± 0.20 SE | 1.75 | verified at 3T, derived at 7T |
| Ins | 1.01 ± 0.09 SE | 1.19 ± 0.07 SD | verified |
| NAAG | todo | 0.94 ± 0.08 SD | verified at 7T |
| NAANAAG | 1.38 ± 0.13 SD | 1.73 ± 0.22 SD | proxy |
| PE | todo | 1.32 ± 0.30 SD | verified at 7T |
| Scyllo | todo | 1.23 ± 0.07 SD | verified at 7T |
| Tau | todo | 2.09 ± 0.04 SD | verified at 7T |

The JSON entries include the source citation, DOI, tissue/resonance notes,
uncertainty type, subject count when available, and any limitations for
proxy or derived values.

## Water-referencing status

`--t1-correction-water-status {uncorrected, corrected, unknown}` (default
`unknown`) records whether the input metabolite maps are already
water-T1-referenced upstream (e.g. by the quantification pipeline's own
internal water-scaling step). This is a required, explicit user choice
rather than an auto-detected heuristic, since MRSinMRS has no enforced
field for it and guessing would silently risk double-correcting or
under-correcting for the water-scaling component. The conservative default
(`unknown`) applies the metabolite-T1-only correction and records the
ambiguity in both the QC report and provenance JSON.

## Outputs

With `--t1-correction literature`, each recording gains:

- `mrsi/orig-t1corr/*_desc-signalt1corr_mrsi.nii.gz` -- the corrected
  metabolite maps (one per requested metabolite), consumed by every
  downstream step (PVC, registration, parcellation) in place of the
  spike-filtered map.
- `confounds/*_desc-t1corr.tsv` -- one row per metabolite: T1, TR, flip
  angle, field strength, computed correction factor, source citation, and
  a `t1_s ± t1_sd_s` sensitivity pair.
- `reports/qc-reports/sub-*_step-t1-correction.html` -- before/after
  slices and the factor table, folded into the combined QC report.
- A `t1_correction` block in the recording's provenance JSON
  (`reports/*_desc-provenance.json`).

With `--t1-correction voxelwise`, each recording instead gains:

- `mrsi/orig-t1corr/*_desc-signalt1corrvoxelwise_mrsi.nii.gz` -- the
  per-voxel-corrected metabolite maps, consumed downstream the same way.
- `confounds/*_desc-t1corrvoxelwise.tsv` -- one row per metabolite: T1,
  TR, field strength, the flip-angle map path, the median correction
  factor, the fraction of voxels excluded for a non-physical factor,
  source citation, and a `t1_s ± t1_sd_s` sensitivity pair (reported as
  the median factor at ±1 SD, since there is no single scalar factor to
  report per metabolite in this mode).
- The same QC report and provenance JSON integration as `literature`
  mode.

See [Basic Usage](usage_basic.md) for the full CLI reference.

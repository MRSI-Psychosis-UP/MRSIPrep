# Experimental features

These features are implemented and opt-in. Their validation is narrower
than the default proton workflow; the table below describes the current
scope. Planned work and feature requests are tracked in the
[issue tracker](https://github.com/MRSI-Psychosis-UP/MRSIPrep/issues).

| Feature | Current validation and limits |
|---|---|
| Non-proton nuclei | Nucleus-aware aliases and thresholds are implemented; 31P and 2H have no curated quality defaults and need explicit thresholds. Proton water-referencing assumptions still need review for other nuclei. |
| Protocol-level T1 correction | Uses tabulated literature values and scalar acquisition metadata; validation is limited to the listed metabolites and protocols. |
| Voxelwise T1 correction | Uses a measured flip-angle map with the same literature T1 values; requires a matching map and has limited acquisition-level validation. |

## Nucleus

MRSIPrep defaults to proton (`1H`) MRSI. Declare a different nucleus either on
the command line:

```bash
  --nucleus 31P
```

or, preferably, once per dataset in `derivatives/mrsi-orig/mrsinmrs.json`,
where it also shows up in every report:

```json
{"CommonMetadata": {"Nucleus": "31P"}}
```

The CLI flag wins when both are present. Common aliases (`proton`, `phosphorus`,
`deuterium`, `P31`, …) are accepted and normalized.

The nucleus selects the voxel-quality thresholds and the metabolite alias
spellings used to locate input maps, and is recorded in the QC report and
`provenance.json`.

**Non-proton nuclei need explicit thresholds.** `31P` and `2H` ship with no
curated `--snr-min`/`--linewidth-max`/`--crlb-max` defaults, because their SNR
regimes differ substantially from proton's and a guessed value would look
authoritative while being wrong. MRSIPrep therefore refuses to start without
them:

```bash
  --nucleus 31P --snr-min 2 --linewidth-max 0.3 --crlb-max 50
```

If you have citation-backed values for a nucleus, contributing them to
`mrsiprep/config/nuclei.json` is a welcome PR — see
[Extending MRSIPrep](extending.md).

See [Preparing inputs](inputs.md) for required quality maps and their units.

## T1 saturation correction

Raw fitted metabolite amplitudes are systematically underestimated when the
acquisition's TR is short relative to a metabolite's own T1 relaxation
time. MRSIPrep does **not** correct for this by default
(`--t1-correction none`); opt in with `--t1-correction literature`
(protocol-level, one factor per metabolite per recording) or
`--t1-correction voxelwise` (per-voxel, using a measured flip-angle map).
See [T1 saturation correction](other_input_derivatives.md#t1-saturation-correction)
for the full requirements, recognized `mrsinmrs.json` keys, supported
metabolites, water-referencing status, and outputs.

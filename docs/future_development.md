# Future Development

This page collects functionality that exists and works today, but is
early-stage: thin validation, limited real-world testing, or a scope the
rest of the pipeline doesn't yet fully support. Treat it as opt-in and
expect rough edges, rather than the default, well-exercised path.

## Nucleus

MRSIPrep defaults to proton (`1H`) MRSI. Declare a different nucleus either on
the command line:

```bash
  --nucleus 31P
```

or, preferably, once per dataset in `mrsinmrs.json` (the `Nucleus` field is part
of the MRSinMRS reporting standard), where it also shows up in every report:

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

**`--quality-metrics` controls which per-voxel quality maps are required
inputs**, separately from the thresholds above: by default all of SNR,
linewidth, and CRLB must be present or the recording fails preflight
validation. If a quantification tool only exports CRLB (common for
non-LCModel pipelines), narrow the requirement instead of having every
recording rejected:

```bash
  --quality-metrics crlb
```

Maps that are present are always applied as voxel-inclusion thresholds
regardless of this flag (via `--snr-min`/`--linewidth-max`/`--crlb-max`);
it only controls whether a *missing* map is an error.

## T1 saturation correction

See [T1 Saturation Correction](usage_t1_correction.md) for the full
documentation of `--t1-correction literature`/`voxelwise`. It is validated
against a curated literature T1 table and a small number of metabolites
(see "Currently supported metabolites" on that page); treat it as opt-in
until it has seen broader validation across acquisition protocols and
metabolite sets.

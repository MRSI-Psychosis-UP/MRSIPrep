# Extending MRSIPrep

Recipes for the three extensions people most often need. Each is deliberately
small: the pipeline is designed so these are additions, not edits to dispatch
logic. See [Architecture](architecture.md) for the wider layout and
[CONTRIBUTING.md](https://github.com/MRSI-Psychosis-UP/MRSIPrep/blob/main/CONTRIBUTING.md)
for the dev/test loop.

## Adding a nucleus (³¹P, ²H, ¹³C, …)

MRSIPrep's processing stages — registration, PVC, parcellation, resampling —
operate on quantified metabolite maps and don't care which nucleus produced
them. What *is* nucleus-specific is metadata: sensible voxel-quality thresholds
and the alias spellings used to find a metabolite's map. Both are data.

**1. Add an entry to `mrsiprep/config/nuclei.json`:**

```json
"13C": {
  "display_name": "Carbon-13",
  "aliases": ["13C", "C13", "carbon"],
  "quality_defaults": {"snr_min": 2.0, "linewidth_max": 0.3, "crlb_max": 40.0},
  "metabolite_aliases": {"Pyruvate": ["Pyruvate", "Pyr"], "Lactate": ["Lactate", "Lac"]},
  "status": "curated",
  "notes": "Thresholds from <study>, <n> subjects at 3T.",
  "source": "https://doi.org/..."
}
```

Set `"quality_defaults": null` with `"status": "uncurated"` if you don't have
citation-backed thresholds. That's what ³¹P and ²H ship as today: MRSIPrep then
*refuses* to run without explicit `--snr-min/--linewidth-max/--crlb-max` rather
than silently applying proton values to a nucleus whose SNR regime is nothing
like proton's. Shipping a guess would look authoritative and be wrong.

The loader validates the entry on import, including that no alias maps to two
nuclei.

**2. Optionally add T1 values** to `mrsiprep/config/t1_literature.json`, keyed
by metabolite and field strength, if users of that nucleus want
`--t1-correction literature`. The signal equation itself is nucleus-agnostic —
only the tabulated T1s are specific.

**3. That's it.** `--nucleus 13C` now works, appears in the report and
`provenance.json`, and drives the thresholds and aliases. Users can also declare
it per-dataset in `mrsinmrs.json`:

```json
{"CommonMetadata": {"Nucleus": "13C"}}
```

**4. Add a test** in `tests/test_nuclei_units.py` alongside the existing ones.

What this does *not* cover: if your nucleus needs a genuinely different
*algorithm* (rather than different constants), that's a backend — see below.
Water-referencing in particular is still proton-shaped; `--t1-correction-water-status`
assumes a ¹H water reference, and gating that per nucleus is not yet done.

## Adding a tissue-segmentation backend

Backends live in a registry in `mrsiprep/workflows/tissue.py`:

```python
def _segment_mytool(config, subject, session, t1_path):
    """Return {label: path} of T1w-space tissue-probability maps."""
    ...

TISSUE_BACKENDS = {
    "existing": _segment_existing,
    "synthseg-fast": _segment_synthseg_fast,
    "mytool": _segment_mytool,          # <- your entry
}
```

Then add `"mytool"` to `--tissue-backend`'s `choices` in `mrsiprep/cli/parser.py`.
No dispatch code changes: `run_tissue_workflow` looks the name up, and an
unknown one already errors listing what's registered.

Wrap the external binary in `mrsiprep/interfaces/`, following e.g.
`interfaces/fsl.py`, and use `utils/subprocess_utils.run_checked()` rather than
calling `subprocess` directly — it handles output capture and error messages
consistently.

Copy a test from `tests/test_extension_points_units.py`; it already covers
"a newly registered backend is dispatched without touching dispatch".

## Adding a parcellation backend

Same shape, in `mrsiprep/workflows/parcellation.py`:

```python
def _parcellate_mine(config, subject, session, mrsi_reference, registration_result, raw_t1, t1_reference):
    """Return a list of ParcellationResult."""
    ...

PARCELLATION_BACKENDS = {..., "mine": _parcellate_mine}
```

Return a **list**, even for a single parcellation — `--chimera-scheme`/`--atlas`
accept comma-separated lists, so every backend returns a list and the
downstream stages fan out over it uniformly.

Build output paths with `io/naming.py`'s helpers and include the `atlas`/`scale`
entities, which is what keeps several parcellations from colliding.

## Adding a registration backend

More involved, because transforms are consumed in several places. Start from
`registration/mrsi_to_t1.py` and `registration/t1_to_mni.py`, and note
`registration/transforms.py` owns the naming and existence checks for transform
files. A new backend must produce both forward and inverse transforms; the
inverse is what projects atlases back into MRSI space.

## Adding a QC feature

QC measures live in `mrsiprep/qc/`, one module per feature. A QC module
computes and returns results; it does not plot or write HTML. The report draws
the results, and the pipeline only connects the two. `mrsiprep/qc/ventricles.py`
is the worked example:

| Layer | Where | Ventricle example |
|---|---|---|
| Compute | `mrsiprep/qc/<feature>.py` | `run_ventricle_qc(raw_maps, reference_ventricles)` returns a `VentricleQC` with per-metabolite Dice, `median_dice` and `passed` |
| Render | `mrsiprep/reports/<feature>_overview.py` | `build_ventricle_qc_sections(...)` calls `run_ventricle_qc` and draws the montage and Dice bars |
| Wire | `mrsiprep/workflows/steps.py` | `_step_ventricle_qc(...)` builds the reference and calls the report, from the reports step |

Guidelines for a new module:

- Take plain inputs (paths, arrays, transform lists) and return a small
  dataclass, so the measure can be called from a notebook or batch script
  without a run config. If the pipeline needs to resolve paths from the
  config, add a thin wrapper next to the plain function, as
  `ventricle_reference_mask` does for `resample_reference_ventricles`.
- Return `None` when an optional input is missing (atlas, segmentation,
  transform) instead of raising, so the QC degrades rather than failing the run.
- Write tables as `desc-<name>` TSVs in the recording's `confounds/` folder
  through `mrsi_derivative(...)`, and add `<name>` to `_CONFOUND_DESCS` in
  `mrsiprep/io/naming.py`.
- Keep pass/fail thresholds as module-level constants with a comment on where
  the value comes from (e.g. `DICE_GOOD = 0.15` and the pilot data behind it).
- Put compute tests in `tests/test_qc_<feature>.py` and rendering tests with
  the report's tests; `tests/test_qc_ventricles.py` and
  `tests/test_ventricle_overview_units.py` show the split.

Called on its own:

```python
from mrsiprep.qc.ventricles import run_ventricle_qc

result = run_ventricle_qc(
    {"CrPCr": "sub-01_ses-01_space-mrsi_met-CrPCr_desc-signal_mrsi.nii.gz"},
    reference_ventricles="sub-01_ses-01_space-mrsi_label-latvent_mask.nii.gz",
)
print(result.median_dice, result.passed)
```

## A note on scope

If you're adding something that doesn't fit these shapes, please open an issue
before writing much code. The stage sequence itself (`STEP_SEQUENCE` in
`workflows/nipype_engine/nodes.py`) is intentionally fixed and linear; changing
it affects caching, the report's PrepParams tab, and the provenance trace together.

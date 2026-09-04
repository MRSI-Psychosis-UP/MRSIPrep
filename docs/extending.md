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

## A note on scope

If you're adding something that doesn't fit these shapes, please open an issue
before writing much code. The stage sequence itself (`STEP_SEQUENCE` in
`workflows/nipype_engine/nodes.py`) is intentionally fixed and linear; changing
it affects caching, the report's PrepParams tab, and the provenance trace together.

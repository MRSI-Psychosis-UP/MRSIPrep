# Architecture

A map of the codebase for people making changes to it. For *using* MRSIPrep see
[Basic Usage](usage_basic.md); for the common extensions see
[Extending MRSIPrep](extending.md).

## The shape of a run

MRSIPrep's input boundary is deliberately narrow: **quantified metabolite maps,
their quality maps (CRLB/SNR/linewidth), and a T1-weighted anatomical.** It does
no spectral fitting and no reconstruction. Everything downstream of that
boundary is indifferent to how the signal was acquired — which is what makes the
pipeline reusable across sequences and, with the nucleus abstraction, across
nuclei.

One run resolves to a list of `(subject, session)` recordings, each processed
through the same fixed stage sequence:

```
prepare → tissue_seg → anat → mrsi → registration → tissue_probmaps →
tissue_qc → pvc → resampling → leakage_qc → synthseg_parc_qc →
parcellation → regional → connectivity → metprofiles → reports
```

**`STEP_SEQUENCE` in `mrsiprep/workflows/nipype_engine/nodes.py` is the
authoritative order.** The static diagram in the report's Preproc tab mirrors
it; if you add a stage, both live there.

## Package responsibilities

| Package | Owns |
|---|---|
| `cli/` | Argument parsing and presets. Builds a `MRSIPrepConfig` and hands off. |
| `config/` | The config dataclass, and the **data tables** (`nuclei.json`, `t1_literature.json`, `presets/`). |
| `io/` | Finding inputs (`bids.py`), validating them, naming outputs (`naming.py`). |
| `workflows/` | Orchestration and the pipeline stages. |
| `mrsi/` | Per-voxel operations on metabolite maps: masks, QC, spike filtering, PVC, T1 correction, resampling. |
| `tissue/` | GM/WM/CSF segmentation and its resampling to the MRSI grid. |
| `registration/` | MRSI↔T1w and T1w↔MNI transforms, and applying them. |
| `parcellation/` | Atlases, label tables, and per-parcel extraction. |
| `connectivity/` | Regional metabolic profiles and the optional connectivity matrix. |
| `reports/` | The per-recording HTML report; one module per tab/section. |
| `interfaces/` | Thin wrappers around external binaries (ANTs, FSL, FreeSurfer, PETPVC, Chimera). |

### `workflows/` in more detail

Split three ways so each file stays readable:

- **`participant.py`** — orchestration only: which recordings to run, in what
  order, and how failures are contained. It re-exports the names below for
  backwards compatibility, so existing imports keep working.
- **`preflight.py`** — the pre-run inventory and the startup table. Read-only:
  it answers "what's present, what's missing, what will be recomputed?" and
  writes nothing.
- **`steps.py`** — the `_step_*` stage functions. Plain functions taking
  `(config, …previous outputs…)`, so they can be called directly *or* wrapped
  as graph nodes.

`workflows/nipype_engine/` wraps those same functions as Nipype nodes for
caching and provenance. The stage logic is not duplicated — the engine calls
into `steps.py`.

## Two conventions worth knowing

**Data, not code.** Anything a domain expert might reasonably want to amend
lives in JSON, validated on load: nucleus definitions (`config/nuclei.json`),
metabolite T1 literature values (`config/t1_literature.json`), published
parameter sets (`config/presets/`). Extending these needs no Python.

**Output naming is a contract.** `io/naming.py` builds every derivative path
from BIDS-style entities (`space`, `atlas`, `scale`, `desc`, …). Because paths
are keyed by those entities, several parcellations can coexist from one run
without colliding. Changing this module changes users' output layout — treat it
as a breaking change.

## Configuration

`MRSIPrepConfig` (`config/settings.py`) is resolved once, then read-only. Its
`__post_init__` runs an explicit sequence: validate required fields → resolve
paths → resolve the nucleus → fill nucleus-derived defaults → validate enums →
resolve remaining derived defaults. Order matters, and the method names say why.

Fields that default to `None` mean **"derive this"** rather than "off" — e.g.
`registration_t1_target` derives from `parcellation_mode`, and the quality
thresholds derive from the nucleus. This is what lets an explicitly-passed flag
or a preset value win automatically: it simply arrives non-`None`.

Precedence, highest first: **explicit CLI flag → `--config-preset` → nucleus
defaults → built-in defaults.**

## Reports and provenance

Every run writes a self-contained HTML report per recording plus a
`provenance.json` recording the resolved config, the resolved path of every
external binary invoked, and a stage-by-stage RAN/SKIPPED trace
(`utils/provenance.py`). The trace is derived from config rather than recorded
live, so it stays consistent with the gating logic in `steps.py` without any
state threading.

# Parcellation and Connectivity Usage

`--parcellation-mode` selects between two full parcellation backends --
Chimera's multi-atlas fusion (`chimera`) or a standardized MNI-space atlas
(`atlas`) -- plus optional perturbation-based connectivity matrices computed
from regional metabolite values.

## Chimera parcellation

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  -v /path/to/freesurfer/license.txt:/opt/freesurfer/license.txt:ro \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --tissue-backend synthseg-fast \
  --parcellation-mode chimera \
  --chimera-scheme LFMIHIFIFF --chimera-scale 3
```

Chimera parcellation requires `recon-all` and a valid `FS_LICENSE`. Mount a
FreeSurfer license file as shown above. MRSIPrep also writes a
legacy-compatible parcel profile archive under
`<out>/mrsiprep/sub-*/ses-*/mrsi/parcel/*_desc-{GM,}metprofiles_mrsi.npz`
(`GMmetprofiles` when PVC ran, `metprofiles` when `--no-pvc` was passed).

## Several parcellations in one run

`--chimera-scheme`, `--chimera-scale`, and `--chimera-grow` each accept a
comma-separated list, the same syntax Chimera's own `--parcodes`/`--scale`/
`--growwm` use. The lists combine as a **cross product**:

```bash
  --parcellation-mode chimera \
  --chimera-scheme LFMIHIFIFF,LFMIHIFIS \
  --chimera-scale 1,3
```

builds four parcellations -- `LFMIHIFIFF` at scales 1 and 3, and `LFMIHIFIS` at
scales 1 and 3 -- from a **single** preprocessing pass. `recon-all` and Chimera
each run once for the whole set, and registration, PVC, and resampling are
shared, so this is far cheaper than four separate runs.

Every parcellation gets its own complete set of derivatives, each keyed by its
atlas and scale so they never overwrite one another:

- a regional metabolite table,
- a metabolite-profile `.npz`,
- CRLB-scaled Monte Carlo profile estimation, and a connectivity matrix when
  `--write-connectivity` is set.

The QC report stays a single file per recording, with one Parcellation section
per parcellation.

> **Scale only multiplies for multi-resolution schemes.** `--chimera-scale`
> applies to the Lausanne cortical parcellation, i.e. schemes whose first
> (cortex) letter is `L`. A scheme that isn't multi-resolution produces one
> parcellation no matter how many scales you list, so the number of outputs can
> be smaller than the nominal cross product.

`--atlas` takes a comma-separated list too, projecting several standardized
atlases in one run:

```bash
  --parcellation-mode atlas --atlas schaefer400,mist197
```

## Bundled MNI atlas

Use a bundled MNI atlas instead of Chimera (no FreeSurfer license required):

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --tissue-backend synthseg-fast \
  --parcellation-mode atlas --atlas chimera-LFMIHIFIS_scale3
```

A custom atlas can be supplied with `--custom-atlas` and its lookup table
with `--custom-atlas-lut`.

## Regional metabolic profiles and connectivity

MRSIPrep always builds a per-parcel regional metabolic profile for
every retained parcel, regardless of `--write-connectivity`: each
metabolite map is perturbed `--connectivity-n-perturbations` times with
CRLB-scaled noise (`--connectivity-sigma-scale`) to propagate quantification
uncertainty into the profile, then z-scored and averaged per parcel. This
profile (written under `<out>/mrsiprep/sub-*/ses-*/connectivity/*_desc-metabolicprofiles_mrsi.npz`)
is a standard regional derivative for every recording and does not require
`--write-connectivity`.

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --parcellation-mode atlas --atlas chimera-LFMIHIFIS_scale3 \
  --write-connectivity \
  --connectivity-method spearman \
  --connectivity-space MNI
```

`--write-connectivity` is the optional add-on: it correlates the
already-computed regional profiles into a regional connectivity (MetSiM)
matrix, without recomputing the perturbations.

See [Basic Usage](usage_basic.md) for the full CLI
reference, including `--parcellation-mode`, `--atlas`, `--custom-atlas`,
`--custom-atlas-lut`, `--chimera-scheme`, `--chimera-scale`,
`--chimera-grow`, `--regional-summary`, `--write-connectivity`,
`--connectivity-method`, `--connectivity-space`,
`--connectivity-n-perturbations`, `--connectivity-sigma-scale`,
`--connectivity-exclude-parcels`, and `--connectivity-max-parcel-id`.

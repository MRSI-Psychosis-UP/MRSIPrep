# Parcellation and Connectivity Usage

`parc-con` mode supports two parcellation backends: Chimera's multi-atlas fusion
or a bundled MNI atlas, plus optional perturbation-based connectivity
matrices computed from regional metabolite values.

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
  --mode parc-con \
  --tissue-backend synthseg-fast \
  --parcellation-mode chimera \
  --chimera-scheme LFMIHIFIFF --chimera-scale 3
```

Chimera parcellation requires `recon-all` and a valid `FS_LICENSE`. Mount a
FreeSurfer license file as shown above. `parc-con` mode also writes a
legacy-compatible parcel profile archive under
`<out>/mrsiprep/sub-*/ses-*/mrsi/parcel/*_desc-{GM,}metprofiles_mrsi.npz`
(`GMmetprofiles` when PVC ran, `metprofiles` when `--no-pvc` was passed).

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
  --mode parc-con \
  --tissue-backend synthseg-fast \
  --parcellation-mode mni --atlas chimera-LFMIHIFIS_scale3
```

A custom atlas can be supplied with `--custom-atlas` and its lookup table
with `--custom-atlas-lut`.

## Regional metabolic profiles and connectivity

`parc-con` mode always builds a per-parcel regional metabolic profile for
every retained parcel, regardless of `--write-connectivity`: each
metabolite map is perturbed `--connectivity-n-perturbations` times with
CRLB-scaled noise (`--connectivity-sigma-scale`) to propagate quantification
uncertainty into the profile, then z-scored and averaged per parcel. This
profile (written under `<out>/mrsiprep/sub-*/ses-*/connectivity/*_desc-metabolicprofiles_mrsi.npz`)
is the standard regional derivative of `parc-con` mode and does not require
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
  --mode parc-con \
  --parcellation-mode mni --atlas chimera-LFMIHIFIS_scale3 \
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

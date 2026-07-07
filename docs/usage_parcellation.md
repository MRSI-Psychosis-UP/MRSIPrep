# Parcellation and Connectivity Usage

`parc-con` mode supports two parcellation backends — Chimera's multi-atlas fusion
or a bundled MNI atlas — plus optional perturbation-based connectivity
matrices computed from regional metabolite values.

## Chimera parcellation

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  -v /path/to/freesurfer/license.txt:/opt/freesurfer/license.txt:ro \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 --session-label V1 \
  --mode parc-con \
  --tissue-backend synthseg-fast \
  --parcellation-mode chimera \
  --chimera-scheme LFMIHIFIFF --chimera-scale 3
```

Chimera parcellation requires `recon-all` and a valid `FS_LICENSE` — mount a
FreeSurfer license file as shown above. `parc-con` mode also writes a
legacy-compatible parcel profile archive under
`<out>/mrsi_parcel/sub-*/ses-*/mrsi/*desc-metprofiles_mrsi.npz`.

## Bundled MNI atlas

Use a bundled MNI atlas instead of Chimera (no FreeSurfer license required):

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 --session-label V1 \
  --mode parc-con \
  --tissue-backend synthseg-fast \
  --parcellation-mode mni --atlas chimera-LFMIHIFIS-3
```

A custom atlas can be supplied with `--custom-atlas` and its lookup table
with `--custom-atlas-lut`.

## Connectivity

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/derivatives:/out \
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 --session-label V1 \
  --mode parc-con \
  --parcellation-mode mni --atlas chimera-LFMIHIFIS-3 \
  --write-connectivity \
  --connectivity-method spearman \
  --connectivity-space MNI
```

`--write-connectivity` builds a regional connectivity matrix from
metabolite values. The matrix is perturbed `--connectivity-n-perturbations`
times with CRLB-scaled noise (`--connectivity-sigma-scale`) to propagate
quantification uncertainty into the connectivity estimate.

## Argument reference

| Argument | Choices / Default | Description |
| --- | --- | --- |
| `--parcellation-mode` | `synthseg`, `chimera`, `mni` / mode-dependent | `mni-norm` only supports `synthseg`; `parc-con` requires `chimera` or `mni`. |
| `--atlas` | `chimera-LFMIHIFIS-3` | Bundled MNI atlas name (used with `--parcellation-mode mni`). |
| `--custom-atlas` | none | Path to a custom atlas NIfTI. |
| `--custom-atlas-lut` | none | Path to the lookup table for `--custom-atlas`. |
| `--chimera-scheme` | `LFMIHIFIFF` | Chimera parcellation scheme: a 10-character code, one letter per supra-region (cortical, subcortical, thalamus, amygdala, hippocampus, hypothalamus, cerebellum, brainstem, gyral WM, WM). |
| `--chimera-scale` | `3` | Chimera parcellation scale. |
| `--chimera-grow` | `2` | Chimera region-growing parameter. |
| `--regional-summary` | `mean`, `median`, `weighted_mean` / `mean` | How voxel values are summarized per parcel. |
| `--write-connectivity` | off | Write a connectivity matrix from regional metabolite values. |
| `--connectivity-method` | `pearson`, `spearman`, `cosine`, `euclidean_distance` / `spearman` | Similarity/distance metric for the connectivity matrix. |
| `--connectivity-space` | `MRSI`, `T1w`, `MNI` / `MRSI` | Space the connectivity matrix is computed in. |
| `--connectivity-n-perturbations` | `50` | Number of CRLB-scaled noise perturbations per metabolite used to build the connectivity matrix. |
| `--connectivity-sigma-scale` | `2.0` | Scale factor applied to the CRLB-derived noise sigma when perturbing metabolite maps for connectivity. |
| `--connectivity-exclude-parcels` | none | Comma-separated substrings; parcels whose name contains any of them are excluded from the connectivity matrix (e.g. `wm-lh,cer-`). |
| `--connectivity-max-parcel-id` | none | Exclude parcels whose label/ID is greater than or equal to this value from the connectivity matrix. |

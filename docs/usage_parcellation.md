# Parcellation, profiles, and connectivity

Choose a parcellation independently of the tissue backend. Every mode
produces regional metabolite summaries and metabolic profiles; a connectivity
matrix is an optional addition with `--write-connectivity`.

| Mode | Labels | Additional requirements |
|---|---|---|
| `synthseg` (default) | Subject-specific SynthSeg anatomical labels | No `recon-all` or FreeSurfer licence |
| `atlas` | Bundled or custom MNI-space atlas projected into subject space | MNI registration; label table for a custom atlas |
| `chimera` | Chimera multi-atlas fusion | `recon-all` and a FreeSurfer licence |

## SynthSeg parcellation (default)

A first run needs no additional parcellation flags. MRSIPrep projects the
SynthSeg labels onto the MRSI grid, computes parcelwise coverage and CRLB
QC, and uses that parcellation for regional summaries and profiles.
The anatomical labels are separate from the GM/WM/CSF probability maps
used for PVC; see [Tissue processing](processing.md).

## Bundled MNI atlas

Use a bundled MNI atlas instead of Chimera (no FreeSurfer license required):

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --tissue-backend synthseg-fast \
  --parcellation-mode atlas --atlas chimera-LFMIHIFIS_scale3
```

For a custom atlas, select `--atlas custom` and provide `--custom-atlas`
and `--custom-atlas-lut`. The image must be a labelled atlas in the supported
MNI space, with integer parcel IDs matching the TSV label table. The table
accepts `parcel_id`/`parcel_name` or `index`/`name` columns. Atlas paths must
be visible inside the container; for files in the BIDS root, use paths under
the standard `/data` mount. High-resolution parcels can disappear on a
coarse MRSI grid, so inspect coverage before choosing an atlas scale.


## Chimera parcellation

See the [Chimera GitHub repository](https://github.com/connectomicslab/chimera)
for the full list of supported parcellation codes (`--chimera-scheme`) and
their constituent atlases.

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --tissue-backend synthseg-fast \
  --parcellation-mode chimera \
  --chimera-scheme LFMIHIFIFF --chimera-scale 3 \
  --fs-license-file /path/to/freesurfer/license.txt
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


## Regional metabolic profiles and connectivity

The regional TSV contains quality-masked summaries per parcel/metabolite.
The `mrsi/parcel/` archive exports a selected summary statistic; the
`connectivity/` archive below contains uncertainty-augmented features. See
[Derivative formats](data_reference.md) for their different dimensions,
masking procedures, and missing-data conventions.

MRSIPrep always builds a per-parcel regional metabolic profile for
every retained parcel, regardless of `--write-connectivity`: each
metabolite map is perturbed `--connectivity-n-perturbations` times with
CRLB-scaled noise (`--connectivity-sigma-scale`) to propagate quantification
uncertainty into the profile, then z-scored and averaged per parcel. This
profile (written under `<out>/mrsiprep/sub-*/ses-*/connectivity/*_desc-metabolicprofiles_mrsi.npz`)
is a standard regional derivative for every recording and does not require
`--write-connectivity`.

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --parcellation-mode atlas --atlas chimera-LFMIHIFIS_scale3 \
  --write-connectivity \
  --connectivity-method spearman
```

`--write-connectivity` is the optional add-on: it correlates the
already-computed regional profiles into a regional connectivity (MetSiM)
matrix, without recomputing the perturbations. These are metabolic-profile
relationships, not anatomical connections or temporal coupling. The current
profile exporter operates on the native MRSI maps and atlas;
`--connectivity-space` is retained as a legacy setting and does not switch
that calculation to MNI space.

See [Command-line arguments](cli_reference.md) for the full CLI
reference, including `--parcellation-mode`, `--atlas`, `--custom-atlas`,
`--custom-atlas-lut`, `--chimera-scheme`, `--chimera-scale`,
`--chimera-grow`, `--regional-summary`, `--write-connectivity`,
`--connectivity-method`, `--connectivity-space`,
`--connectivity-n-perturbations`, `--connectivity-sigma-scale`,
`--connectivity-exclude-parcels`, and `--connectivity-max-parcel-id`.

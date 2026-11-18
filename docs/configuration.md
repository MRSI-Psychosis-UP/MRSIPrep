# Configuration and presets

Start with the [first-run tutorial](usage_basic.md), then select settings
for your acquisition. The [CLI reference](cli_reference.md) is generated
from the parser and lists all available arguments.

## Main choices

| Choice | Default | Guide |
|---|---|---|
| Acquisition metadata | Required at `derivatives/mrsi-orig/mrsinmrs.json`, or selected with `--mrsinmrs-file` | [Metadata specification](inputs.md#acquisition-metadata-mrsinmrsjson) |
| Acquired nucleus | `1H`, unless declared in `mrsinmrs.json` | [Inputs](inputs.md); [Experimental features](future_development.md) for other nuclei |
| Required quality maps | SNR, linewidth, and per-metabolite CRLB | [Input requirements](inputs.md#required-quality-maps-versus-inclusion-thresholds) |
| Tissue backend | `synthseg-fast` | [Tissue processing and PVC](processing.md) |
| Spike filtering / PVC | Enabled | [Processing settings](processing.md) |
| T1 saturation correction | Disabled | [Experimental features](future_development.md) |
| Registration backend | ANTs | [Registration and output spaces](usage_normalization.md) |
| Final output space | `MNI152NLin2009cAsym`, native-resolution-derived spacing | [Output spaces](usage_normalization.md) |
| Parcellation | `synthseg` | [Parcellation and profiles](usage_parcellation.md) |
| Connectivity matrix | Disabled; regional profiles still written | [Connectivity](usage_parcellation.md#regional-metabolic-profiles-and-connectivity) |
| Concurrent recordings / threads | `--nproc 1`, `--nthreads 16`, adjusted to CPU budget | [Batch runs](running.md) |

Registration target defaults also depend on parcellation: `brain` for
SynthSeg, `brain-csf` for atlas/Chimera. Tissue segmentation, anatomical
parcellation, and output-space selection are separate settings; changing
one does not imply the others are disabled.

## Published-study presets

List the available configurations and their source citations:

```bash
docker run --rm mrsiup/mrsiprep:cpu --list-presets
```

Use a preset while keeping the input paths explicit:

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --config-preset nature-comms-2025 \
  --nthreads 8 --nproc 1 \
  --fs-license-file /path/to/freesurfer/license.txt
```

That preset selects Chimera and the `existing` tissue backend, among other
settings. It requires the corresponding CAT12/skull-strip inputs and a
FreeSurfer licence. A preset reproduces processing parameters; it does not
make a dataset match the acquisition or population of the source study.
The report credits the preset's publication.

Precedence is **explicit CLI flag → preset → nucleus-specific defaults →
built-in defaults**. Inspect the resolved configuration in the provenance
JSON when comparing runs. An explicit disabling flag, such as `--no-pvc`,
overrides a preset in the same way as a numeric setting.

`--config-preset` also accepts a JSON file containing configuration field
names, such as `snr_min` and `parcellation_mode`. `_citation` is reserved for
source metadata; unknown fields are rejected. With plain Docker, paths in
arguments and JSON must refer to mounted container paths. The wrapper
automatically mounts the BIDS and output roots and its supported special
paths; arbitrary configuration files outside those mounts need a bind mount.

## Command builder

The [Command builder](installation.md#option-a-command-builder-recommended) is the recommended
way to assemble a run in a browser form. Follow Installation's Option A to
install and launch it, then choose the settings described on this page and
copy the generated command into a terminal.

## Preserve a configuration

Record the command, resolved provenance JSON, and container version or
digest with your results. The `cpu` image tag can change between pulls;
an immutable digest identifies the exact image used. Keep acquisition
metadata and study-level QC inclusion criteria with that record. See
[Processing methods](methods.md) for limitations of resampling and
Monte Carlo reproducibility.

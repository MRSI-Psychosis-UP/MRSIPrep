# Installation

MRSIPrep is distributed as a Docker image. There is no supported host
installation of the pipeline itself.

```bash
docker pull fedlucchetti/mrsiprep:cpu
```

The image bundles ANTs, FSL (FAST only), FreeSurfer (`recon-all`,
`mri_synthseg`, `mri_vol2vol`), PETPVC, and Chimera. It does not include a
FreeSurfer license file — mount your own and set `FS_LICENSE`:

```bash
docker run --rm \
  -v /path/to/bids:/data:ro \
  -v /path/to/bids/derivatives:/out \
  -v /path/to/freesurfer/license.txt:/opt/freesurfer/license.txt:ro \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  fedlucchetti/mrsiprep:cpu \
  /data /out participant \
  --participant-label S001 \
  --session-label V1 \
  --mode mni-norm \
  --nthreads 8
```

You will still need a BIDS dataset with already-quantified MRSI maps; see
[Basic Usage](usage_basic.md) for the full command-line walkthrough.

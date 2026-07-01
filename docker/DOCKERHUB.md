# MRSIPrep

BIDS App for preprocessing already-quantified whole-brain MRSI maps:
biharmonic spike repair, MRSI↔T1w registration, tissue segmentation
(SynthSeg/FAST), partial-volume correction, T1w↔MNI normalization, and
Chimera/MNI-atlas regional profile extraction.

Full documentation, CLI options, and output layout:
https://github.com/MRSI-Psychosis-UP/mrsiprep

## Pull

```bash
docker pull fedlucchetti/mrsiprep:cpu
```

Bundles ANTs, FSL (FAST only), FreeSurfer (`recon-all`, `mri_synthseg`,
`mri_vol2vol`), PETPVC, and Chimera. No FreeSurfer license is included —
mount your own and set `FS_LICENSE`.

## Run

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

*MRSIPrep* is a preprocessing and derivative-generation pipeline for already
quantified whole-brain MRSI maps, run as a BIDS App via Docker. Its default light mode normalizes MRSI
maps and uses fast SynthSeg cortical parcellation for parcelwise anatomical
coverage and CRLB reporting. `parc-con` mode adds SynthSeg+FAST tissue maps,
PETPVC, and Chimera/MNI-atlas regional profile extraction for metabolic connectivty computation.

## License

CHUV academic non-commercial research license. See the LICENSE file in the
source repository.

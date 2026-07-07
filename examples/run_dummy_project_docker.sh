#!/usr/bin/env bash
set -euo pipefail

: "${FS_LICENSE:?Set FS_LICENSE to your FreeSurfer license file before running this script.}"

docker/update_mrsiprep_image.sh

docker run --rm \
  -v /home/flucchetti/Connectome/BIDS/Dummy-Project:/data:ro \
  -v /home/flucchetti/Connectome/BIDS/Dummy-Project/derivatives:/out \
  -v "${FS_LICENSE}:/opt/freesurfer/license.txt:ro" \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  mrsiprep:cpu \
  /data /out participant \
  --participant-label CHUVUP013 \
  --session-label V1 \
  --mode full \
  --tissue-backend synthseg-fast \
  --registration-t1-target brain-csf \
  --parcellation-mode mni \
  --nthreads 4 \
  --verbose 2

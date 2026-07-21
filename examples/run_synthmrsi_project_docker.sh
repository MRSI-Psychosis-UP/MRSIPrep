#!/usr/bin/env bash
set -euo pipefail

: "${FS_LICENSE:?Set FS_LICENSE to your FreeSurfer license file before running this script.}"
: "${SYNTHMRSI_PROJECT_DIR:?Set SYNTHMRSI_PROJECT_DIR to your local SynthMRSI-Project BIDS root before running this script.}"

docker pull mrsiup/mrsiprep:cpu

docker run --rm \
  -v "${SYNTHMRSI_PROJECT_DIR}:/data:ro" \
  -v "${SYNTHMRSI_PROJECT_DIR}/derivatives:/out" \
  -v "${FS_LICENSE}:/opt/freesurfer/license.txt:ro" \
  -e FS_LICENSE=/opt/freesurfer/license.txt \
  mrsiup/mrsiprep:cpu \
  /data /out participant \
  --session-label 01 \
  --mode mni-norm \
  --t1 acq-mprage_T1w \
  --metabolites NAANAAG,GPCPCh,CrPCr,GluGln,Ins \
  --ref-met CrPCr \
  --nthreads 8 --nproc 2 --verbose 2

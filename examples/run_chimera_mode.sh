#!/usr/bin/env bash
set -euo pipefail

mrsiprep "$1" "$2" participant \
  --participant-label S001 \
  --session-label V1 \
  --mode full \
  --registration-t1-target brain-csf \
  --tissue-backend synthseg-fast \
  --parcellation-mode chimera \
  --chimera-scheme LFMIHIFIS \
  --chimera-scale 3 \
  --write-connectivity

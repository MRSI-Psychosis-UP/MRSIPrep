#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-${APP_IMAGE:-mrsiprep:cpu}}"
REQUIRE_PETPVC="${REQUIRE_PETPVC:-1}"
REQUIRE_CHIMERA="${REQUIRE_CHIMERA:-1}"
REQUIRE_FSL="${REQUIRE_FSL:-1}"
REQUIRE_FREESURFER="${REQUIRE_FREESURFER:-1}"

docker run --rm \
  --entrypoint /usr/local/bin/mrsiprep-check-neurodeps \
  -e "REQUIRE_FSL=${REQUIRE_FSL}" \
  -e "REQUIRE_FREESURFER=${REQUIRE_FREESURFER}" \
  -e "REQUIRE_PETPVC=${REQUIRE_PETPVC}" \
  -e "REQUIRE_CHIMERA=${REQUIRE_CHIMERA}" \
  "${IMAGE}"

printf 'Container dependency test passed: %s\n' "${IMAGE}"

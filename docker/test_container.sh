#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-${APP_IMAGE:-mrsiprep:cpu}}"
REQUIRE_PETPVC="${REQUIRE_PETPVC:-1}"
REQUIRE_CHIMERA="${REQUIRE_CHIMERA:-1}"
REQUIRE_FSL="${REQUIRE_FSL:-1}"
REQUIRE_FREESURFER="${REQUIRE_FREESURFER:-1}"
# nipype is only installed at the thin app layer (Dockerfile), not the deps
# layer (Dockerfile.cpu-deps) -- default to requiring it, but skip when
# testing a *-deps image directly (build_private_deps.sh/finalize_manual_deps.sh
# call this against the deps image, before the app layer adds nipype).
case "${IMAGE}" in
  *-deps:*|*deps*) REQUIRE_NIPYPE="${REQUIRE_NIPYPE:-0}" ;;
  *) REQUIRE_NIPYPE="${REQUIRE_NIPYPE:-1}" ;;
esac

docker run --rm \
  --entrypoint /usr/local/bin/mrsiprep-check-neurodeps \
  -e "REQUIRE_FSL=${REQUIRE_FSL}" \
  -e "REQUIRE_FREESURFER=${REQUIRE_FREESURFER}" \
  -e "REQUIRE_PETPVC=${REQUIRE_PETPVC}" \
  -e "REQUIRE_CHIMERA=${REQUIRE_CHIMERA}" \
  -e "REQUIRE_NIPYPE=${REQUIRE_NIPYPE}" \
  "${IMAGE}"

printf 'Container dependency test passed: %s\n' "${IMAGE}"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER_NAME="${DEPS_CONTAINER:-mrsiprep-deps-install}"
DEPS_IMAGE="${DEPS_IMAGE:-mrsiprep-deps:ubuntu22.04-cpu}"

if ! docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  printf 'Manual dependency container not found: %s\n' "${CONTAINER_NAME}" >&2
  exit 2
fi

# Refresh utilities before committing the existing installation container.
docker cp \
  "${ROOT_DIR}/docker/check_neurodeps.sh" \
  "${CONTAINER_NAME}:/usr/local/bin/mrsiprep-check-neurodeps"

docker commit "${CONTAINER_NAME}" "${DEPS_IMAGE}" >/dev/null

REQUIRE_FSL=1 REQUIRE_FREESURFER=1 REQUIRE_PETPVC=1 REQUIRE_CHIMERA=1 \
  "${ROOT_DIR}/docker/test_container.sh" "${DEPS_IMAGE}"

printf 'Final private dependency image ready: %s\n' "${DEPS_IMAGE}"
printf 'The installation container remains available as %s until you remove it.\n' "${CONTAINER_NAME}"
printf 'Next: docker/build_cpu_image.sh (prunes %s into mrsiprep-deps:cpu and builds the app image)\n' "${DEPS_IMAGE}"

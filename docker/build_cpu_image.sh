#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DEPS_IMAGE="${SOURCE_DEPS_IMAGE:-mrsiprep-deps:ubuntu22.04-cpu}"
DEPS_IMAGE="${DEPS_IMAGE:-mrsiprep-deps:cpu}"
APP_IMAGE="${APP_IMAGE:-mrsiprep:cpu}"

if ! docker image inspect "${SOURCE_DEPS_IMAGE}" >/dev/null 2>&1; then
  printf 'Source dependency image does not exist: %s\n' "${SOURCE_DEPS_IMAGE}" >&2
  exit 2
fi

docker buildx build --load \
  -f "${ROOT_DIR}/Dockerfile.cpu-deps" \
  --build-arg "SOURCE_DEPS_IMAGE=${SOURCE_DEPS_IMAGE}" \
  -t "${DEPS_IMAGE}" \
  "${ROOT_DIR}"

DEPS_IMAGE="${DEPS_IMAGE}" APP_IMAGE="${APP_IMAGE}" \
  "${ROOT_DIR}/docker/update_mrsiprep_image.sh"

"${ROOT_DIR}/docker/test_container.sh" "${APP_IMAGE}"

printf 'Full CPU image ready: %s\n' "${APP_IMAGE}"
docker image ls "${APP_IMAGE}"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS_IMAGE="${DEPS_IMAGE:-mrsiprep-deps:cpu}"
APP_IMAGE="${APP_IMAGE:-mrsiprep:cpu}"

if ! docker image inspect "${DEPS_IMAGE}" >/dev/null 2>&1; then
  printf 'Dependency image does not exist: %s\n' "${DEPS_IMAGE}" >&2
  printf 'Run docker/build_cpu_image.sh first (or docker/finalize_manual_deps.sh for the manual workflow) to produce it from mrsiprep-deps:ubuntu22.04-cpu.\n' >&2
  exit 2
fi

docker buildx build --load \
  -f "${ROOT_DIR}/Dockerfile" \
  --build-arg "DEPS_IMAGE=${DEPS_IMAGE}" \
  -t "${APP_IMAGE}" \
  "${ROOT_DIR}"

docker run --rm --entrypoint /usr/bin/python3 "${APP_IMAGE}" -c \
  'import mrsiprep; print("MRSIPrep import OK")'

printf 'Updated application image ready: %s\n' "${APP_IMAGE}"

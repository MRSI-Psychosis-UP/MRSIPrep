#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${NEURODEPS_ENV_FILE:-${ROOT_DIR}/docker/private-neurodeps.env}"
DEPS_IMAGE="${DEPS_IMAGE:-mrsiprep-deps:ubuntu22.04-cpu}"
REQUIRE_PETPVC="${REQUIRE_PETPVC:-1}"
REQUIRE_CHIMERA="${REQUIRE_CHIMERA:-1}"

if [[ ! -f "${ENV_FILE}" ]]; then
  printf 'Private dependency configuration not found: %s\n' "${ENV_FILE}" >&2
  printf 'Create it from docker/private-neurodeps.env.example.\n' >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

require_any() {
  local label="$1"
  shift
  local variable
  for variable in "$@"; do
    if [[ -n "${!variable:-}" ]]; then
      return 0
    fi
  done
  printf 'No source configured for %s (%s).\n' "${label}" "$*" >&2
  exit 2
}

require_any ANTs ANTS_URL ANTS_ARCHIVE
require_any FSL FSL_URL FSL_INSTALLER_URL FSL_ARCHIVE
require_any FreeSurfer FREESURFER_URL FREESURFER_ARCHIVE
if [[ "${REQUIRE_PETPVC}" == "1" ]]; then
  require_any PETPVC PETPVC_URL PETPVC_ARCHIVE
fi
if [[ "${REQUIRE_CHIMERA}" == "1" ]]; then
  require_any Chimera CHIMERA_URL CHIMERA_ARCHIVE
fi

secrets=(--secret "id=neurodeps_env,src=${ENV_FILE}")

add_archive_secret() {
  local id="$1"
  local path="$2"
  if [[ -n "${path}" ]]; then
    if [[ ! -f "${path}" ]]; then
      printf 'Archive for %s not found: %s\n' "${id}" "${path}" >&2
      exit 2
    fi
    secrets+=(--secret "id=${id},src=${path}")
  fi
}

add_archive_secret ants_archive "${ANTS_ARCHIVE:-}"
add_archive_secret fsl_archive "${FSL_ARCHIVE:-}"
add_archive_secret freesurfer_archive "${FREESURFER_ARCHIVE:-}"
add_archive_secret petpvc_archive "${PETPVC_ARCHIVE:-}"
add_archive_secret chimera_archive "${CHIMERA_ARCHIVE:-}"

docker buildx build --load \
  -f "${ROOT_DIR}/Dockerfile.deps" \
  -t "${DEPS_IMAGE}" \
  --build-arg "REQUIRE_PETPVC=${REQUIRE_PETPVC}" \
  --build-arg "REQUIRE_CHIMERA=${REQUIRE_CHIMERA}" \
  "${secrets[@]}" \
  "${ROOT_DIR}"

REQUIRE_PETPVC="${REQUIRE_PETPVC}" REQUIRE_CHIMERA="${REQUIRE_CHIMERA}" \
  "${ROOT_DIR}/docker/test_container.sh" "${DEPS_IMAGE}"

printf 'Private dependency image ready: %s\n' "${DEPS_IMAGE}"

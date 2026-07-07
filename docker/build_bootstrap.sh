#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAP_IMAGE="${BOOTSTRAP_IMAGE:-mrsiprep-bootstrap:ubuntu22.04-cpu}"

docker buildx build --load \
  -f "${ROOT_DIR}/Dockerfile.bootstrap" \
  -t "${BOOTSTRAP_IMAGE}" \
  "${ROOT_DIR}"

REQUIRE_FSL=0 REQUIRE_FREESURFER=0 REQUIRE_PETPVC=1 REQUIRE_CHIMERA=1 \
  "${ROOT_DIR}/docker/test_container.sh" "${BOOTSTRAP_IMAGE}"

printf 'Bootstrap image ready: %s\n' "${BOOTSTRAP_IMAGE}"
printf 'Next: docker/enter_manual_deps.sh\n'

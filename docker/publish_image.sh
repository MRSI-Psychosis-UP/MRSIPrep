#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP_IMAGE="${APP_IMAGE:-mrsiprep:cpu}"
DOCKERHUB_REPO="${DOCKERHUB_REPO:-}"
TAG="${TAG:-cpu}"
SAVE_DIR="${SAVE_DIR:-${ROOT_DIR}/dist}"
SKIP_SAVE="${SKIP_SAVE:-0}"
SKIP_PUSH="${SKIP_PUSH:-0}"

usage() {
  cat <<'EOF'
Usage: docker/publish_image.sh [-r repo] [-t tag] [-o output_dir] [--no-save] [--no-push]

Saves the local MRSIPrep image to a compressed tarball and/or pushes it to
Docker Hub.

Options:
  -r, --repo REPO      Docker Hub repo to publish to, e.g. myuser/mrsiprep.
                        Can also be set via DOCKERHUB_REPO.
  -t, --tag TAG        Tag to publish under (default: cpu). Also set via TAG.
  -o, --output DIR     Directory to write the .tar.gz to (default: ./dist).
                        Also set via SAVE_DIR.
      --no-save        Skip writing the local tarball.
      --no-push        Skip tagging/pushing to Docker Hub.

Environment:
  APP_IMAGE            Local image to publish (default: mrsiprep:cpu).

Examples:
  docker/publish_image.sh -r myuser/mrsiprep -t cpu
  docker/publish_image.sh --no-push                  # local tarball only
  SKIP_SAVE=1 docker/publish_image.sh -r myuser/mrsiprep
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--repo) DOCKERHUB_REPO="$2"; shift 2 ;;
    -t|--tag) TAG="$2"; shift 2 ;;
    -o|--output) SAVE_DIR="$2"; shift 2 ;;
    --no-save) SKIP_SAVE=1; shift ;;
    --no-push) SKIP_PUSH=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! docker image inspect "${APP_IMAGE}" >/dev/null 2>&1; then
  printf 'Local image not found: %s\n' "${APP_IMAGE}" >&2
  printf 'Build it first, e.g. docker/build_cpu_image.sh or docker/update_mrsiprep_image.sh.\n' >&2
  exit 2
fi

if [[ "${SKIP_PUSH}" != "1" && -z "${DOCKERHUB_REPO}" ]]; then
  printf 'No Docker Hub repo given. Pass -r/--repo or set DOCKERHUB_REPO, or use --no-push.\n' >&2
  usage >&2
  exit 2
fi

printf 'Publishing %s\n' "${APP_IMAGE}"
docker image ls "${APP_IMAGE}"

if [[ "${SKIP_SAVE}" != "1" ]]; then
  mkdir -p "${SAVE_DIR}"
  out_name="$(printf '%s' "${APP_IMAGE}" | tr '/:' '__')"
  out_path="${SAVE_DIR}/${out_name}.tar.gz"
  printf 'Saving local tarball to %s (this can take a while for large images)...\n' "${out_path}"
  docker save "${APP_IMAGE}" | gzip -1 > "${out_path}"
  printf 'Saved: %s\n' "${out_path}"
  ls -lh "${out_path}"
fi

if [[ "${SKIP_PUSH}" != "1" ]]; then
  remote_ref="${DOCKERHUB_REPO}:${TAG}"
  printf 'Tagging %s as %s\n' "${APP_IMAGE}" "${remote_ref}"
  docker tag "${APP_IMAGE}" "${remote_ref}"

  printf 'Pushing %s to Docker Hub...\n' "${remote_ref}"
  printf 'If this fails with an auth error, run "docker login" first.\n'
  docker push "${remote_ref}"

  printf 'Published: %s\n' "${remote_ref}"
  printf 'Anyone can now pull it with: docker pull %s\n' "${remote_ref}"
fi

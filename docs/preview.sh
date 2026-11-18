#!/usr/bin/env bash
# Build and serve the docs locally, matching the RTD/CI build (same flags,
# same deps) so what you see here is what gets published.
#
# Usage:
#   docs/preview.sh            # build once, serve on http://127.0.0.1:8000
#   docs/preview.sh --watch    # rebuild on file changes (requires sphinx-autobuild)
#   docs/preview.sh --port 8080

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PORT=8000
WATCH=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --watch) WATCH=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

VENV_DIR=".venv-docs"
if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating docs venv at $VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

pip install -q -r docs/requirements.txt

BUILD_DIR="docs/_build/html"

if [[ "$WATCH" -eq 1 ]]; then
  pip install -q sphinx-autobuild
  exec python -m sphinx_autobuild docs "$BUILD_DIR" \
    --port "$PORT" \
    --jobs auto
else
  python -m sphinx -b html -j auto -W --keep-going docs "$BUILD_DIR"
  echo "Built. Serving at http://127.0.0.1:$PORT"
  cd "$BUILD_DIR"
  exec python3 -m http.server "$PORT"
fi

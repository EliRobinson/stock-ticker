#!/usr/bin/env bash
# Run the stack for local dev. Ctrl+C stops it and cleans up automatically —
# same teardown as scripts/down.sh, so images never pile up between runs.
set -euo pipefail
cd "$(dirname "$0")/.."

trap './scripts/down.sh' EXIT

docker compose up --build

#!/usr/bin/env bash
# Stop this repo's stack and remove the images it built (api, migrate,
# worker), so they don't pile up between runs. Never touches base images
# (postgres, node) or any other project's containers/images.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose down --rmi local --remove-orphans

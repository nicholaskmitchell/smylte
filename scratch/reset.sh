#!/usr/bin/env bash
# Wipe the scratch collection tree and start clean. Never touches ~/radicale.
set -euo pipefail
cd "$(dirname "$0")"
docker compose down
rm -rf ./data/collections
mkdir -p ./data/collections
echo "scratch storage wiped; run: docker compose up -d"

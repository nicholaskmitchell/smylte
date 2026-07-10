#!/usr/bin/env bash
# Delete Radicale's item/sync-token cache to simulate a pruned/invalid sync
# token (spec invariant #6). Radicale rebuilds the cache lazily; existing sync
# tokens become invalid, so the app must fall back to a full resync.
set -euo pipefail
cd "$(dirname "$0")"
find ./data/collections -name '.Radicale.cache' -type d -exec rm -rf {} + 2>/dev/null || true
echo "dropped .Radicale.cache — next sync-collection REPORT should 4xx the old token"

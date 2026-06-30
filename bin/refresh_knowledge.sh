#!/bin/bash
# catalyst-tracker — knowledge-corpus refresh. Republishes the static trigger
# thresholds (idempotent; self-heals deletions) and fetch+verifies the live
# readings into ~/ObsidianVault/knowledge/ai-infra/. The vault syncs via
# Syncthing, so this is read-only against the repo (no git commit/push).
#
# Usage: refresh_knowledge.sh            # sync + fetch (write)
#        refresh_knowledge.sh --dry-run  # preview both, write nothing
set -euo pipefail

cd "$HOME/catalyst-tracker"
export PATH="$HOME/.hermes/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
set -a
# shellcheck disable=SC1090
source "$HOME/.catalyst.env"
set +a

mkdir -p "$HOME/catalyst-tracker/logs"
LOG="$HOME/catalyst-tracker/logs/knowledge.log"

{
  echo "=== $(date -u +%FT%TZ) knowledge refresh ==="
  .venv/bin/python -m scripts.sync_knowledge "$@"
  .venv/bin/python -m scripts.fetch_knowledge "$@"
  echo "=== $(date -u +%FT%TZ) done ==="
} >> "$LOG" 2>&1

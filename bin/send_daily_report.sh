#!/bin/bash
# catalyst-tracker — daily digest sender. Sources secrets and e-mails the
# priority-ordered digest. Read-only against state (no commit/push).
#
# Usage: send_daily_report.sh           # send
#        send_daily_report.sh --dry-run # print
set -euo pipefail

cd "$HOME/catalyst-tracker"
export PATH="$HOME/.hermes/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
set -a
# shellcheck disable=SC1090
source "$HOME/.catalyst.env"
set +a

mkdir -p "$HOME/catalyst-tracker/logs"
LOG="$HOME/catalyst-tracker/logs/daily_report.log"

{
  echo "=== $(date -u +%FT%TZ) daily report ==="
  .venv/bin/python scripts/daily_report.py "$@"
  echo "=== $(date -u +%FT%TZ) done ==="
} >> "$LOG" 2>&1

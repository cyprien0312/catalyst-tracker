#!/bin/bash
# catalyst-tracker — daily news roll-up sender. Companion to
# send_daily_report.sh: the digest reports signal *state*, this reports the
# day's actual alert *content* so per-alert e-mails can stay muted.
# Read-only against state (no commit/push, no state writes at all).
#
# Usage: send_news_report.sh           # send (skips if the window is empty)
#        send_news_report.sh --dry-run # print
set -euo pipefail

cd "$HOME/catalyst-tracker"
export PATH="$HOME/.hermes/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
set -a
# shellcheck disable=SC1090
source "$HOME/.catalyst.env"
set +a

mkdir -p "$HOME/catalyst-tracker/logs"
LOG="$HOME/catalyst-tracker/logs/news_report.log"

{
  echo "=== $(date -u +%FT%TZ) news report ==="
  .venv/bin/python scripts/news_report.py "$@"
  echo "=== $(date -u +%FT%TZ) done ==="
} >> "$LOG" 2>&1

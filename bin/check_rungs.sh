#!/bin/bash
# catalyst-tracker — buy-plan rung/regime alerter (hourly cron). Emails the
# moment NDX crosses a ladder rung or the A/B regime flips, instead of
# waiting for the 09:00 digest. Writes only to state/tracker.sqlite (seen +
# alerts rows); no commit/push — the :30-cadence catalyst runs sweep the
# state change into git within minutes.
#
# Usage: check_rungs.sh           # check + email
#        check_rungs.sh --dry-run # print would-be alerts
set -euo pipefail

cd "$HOME/catalyst-tracker"
export PATH="$HOME/.hermes/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
set -a
# shellcheck disable=SC1090
source "$HOME/.catalyst.env"
set +a

mkdir -p "$HOME/catalyst-tracker/logs"
LOG="$HOME/catalyst-tracker/logs/rung_alert.log"

{
  echo "=== $(date -u +%FT%TZ) rung check ==="
  .venv/bin/python scripts/rung_alert.py "$@"
} >> "$LOG" 2>&1

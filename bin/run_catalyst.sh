#!/bin/bash
# Catalyst tracker — cron wrapper. Used by the local production deployment
# (see README.md "Production deployment" section).
#
# Usage:
#   run_catalyst.sh <catalyst_module>
#   e.g.  run_catalyst.sh c3_openai
#
# Required env (sourced from ~/.catalyst.env):
#   SEC_USER_AGENT, GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_TO,
#   CATALYST_LLM_ENABLED, CATALYST_LLM_CLAUDE_BIN, ...
#
# Side effects:
#   - Runs `python -m catalysts.<module>` then `scripts/build_dashboard.py`
#   - Appends to logs/<module>.log (gitignored)
#   - Commits + pushes updated state/ and docs/ to origin/main
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <catalyst_module>" >&2
  exit 2
fi
CATALYST="$1"

cd "$HOME/catalyst-tracker"

# cron has a minimal PATH; ensure claude CLI (under ~/.hermes/node/bin) is reachable
export PATH="$HOME/.hermes/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
set -a
# shellcheck disable=SC1090
source "$HOME/.catalyst.env"
set +a

mkdir -p "$HOME/catalyst-tracker/logs"
LOG="$HOME/catalyst-tracker/logs/${CATALYST}.log"

{
  echo "=== $(date -u +%FT%TZ) start ${CATALYST} ==="
  .venv/bin/python -m "catalysts.${CATALYST}"
  .venv/bin/python scripts/build_dashboard.py
  echo "=== $(date -u +%FT%TZ) end ${CATALYST} ==="
} >> "$LOG" 2>&1

# Commit + push state + dashboard. Mirrors .github/actions/commit-state behavior:
# pull --rebase retries to survive races with parallel catalyst runs.
COMMIT_FILES=(state/tracker.sqlite docs/index.html docs/thresholds.html docs/data/status.json)
{
  git add "${COMMIT_FILES[@]}" 2>/dev/null || true
  if git diff --cached --quiet; then
    echo "$(date -u +%FT%TZ) nothing to commit"
    exit 0
  fi
  git -c user.name="catalyst-bot" -c user.email="bot@openclaw.local" \
      commit -m "state: ${CATALYST} run $(date -u +%FT%TZ)"
  for attempt in 1 2 3 4 5; do
    if git push origin main; then
      echo "$(date -u +%FT%TZ) pushed on attempt ${attempt}"
      exit 0
    fi
    echo "$(date -u +%FT%TZ) push attempt ${attempt} failed; rebasing"
    git fetch origin
    git rebase origin/main || { git rebase --abort || true; exit 1; }
    sleep $((attempt * 2))
  done
  echo "$(date -u +%FT%TZ) exhausted push attempts" >&2
  exit 1
} >> "$LOG" 2>&1

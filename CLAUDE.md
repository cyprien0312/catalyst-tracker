# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`catalyst-tracker` is a Python 3.11 monitoring pipeline that scans SEC filings, RSS feeds, XBRL financial data, and ISO interconnection-queue snapshots for five "AI infrastructure bubble-stress" signals (C1–C5) and emails alerts via Gmail SMTP. State lives in SQLite (`state/tracker.sqlite`); the dashboard is static HTML in `docs/` published to GitHub Pages.

Production deployment is **local cron on this host** (not GitHub Actions). The workflows in `.github/workflows/` have their `schedule:` blocks commented out — only `workflow_dispatch` and `tests.yml` are live. See README "Why a single host instead of GitHub Actions" for rationale (mainly: reusing the long-lived `claude` CLI session for free LLM explanations).

## Commands

```bash
# Setup
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# Tests
.venv/bin/pytest -v                          # all
.venv/bin/pytest tests/test_c4.py -v         # one file
.venv/bin/pytest -k "ratio_cross" -v         # match by name

# Run a catalyst (dry-run prints to stdout, no email, no state write of alerts)
.venv/bin/python -m catalysts.c1_depreciation --dry-run
.venv/bin/python -m catalysts.c2_neoclouds   --dry-run --no-prices
.venv/bin/python -m catalysts.c3_openai      --dry-run --no-edgar
.venv/bin/python -m catalysts.c5_grid        --dry-run --skip-iso  # offline-friendly

# Verbosity
LOG_LEVEL=DEBUG .venv/bin/python -m catalysts.c3_openai --dry-run

# Dashboard rebuild (writes docs/index.html, docs/thresholds.html, docs/data/status.json)
.venv/bin/python scripts/build_dashboard.py

# Smoke tests before prod changes
.venv/bin/python scripts/llm_smoke.py     # verifies `claude` CLI envelope still matches lib/llm.py parsing
.venv/bin/python scripts/test_alert.py    # sends an [OPS-TEST] email via Gmail SMTP

# Inspect state
sqlite3 state/tracker.sqlite ".tables"
sqlite3 state/tracker.sqlite ".schema c4_xbrl"
sqlite3 state/tracker.sqlite "SELECT ts, catalyst, severity, subject FROM alerts ORDER BY ts DESC LIMIT 20"
```

For real runs, secrets must be loaded from `~/.catalyst.env` (outside the repo) — at minimum `SEC_USER_AGENT`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_TO`. `set -a; source ~/.catalyst.env; set +a` before invoking.

## Architecture

### Module shape

Each `catalysts/cN_*.py` is a standalone module exposing a class (subclass of `catalysts.base.CatalystBase`) plus `__main__` glue via `catalysts.base.run_cli`. The CLI parses `--dry-run` and catalyst-specific flags, instantiates the catalyst, calls `run() -> list[Alert]`, then either prints or emails. **Adding a new flag means passing an `extra_args` callable to `run_cli`** — see `c2_neoclouds.py` for the pattern.

`Alert` (`catalysts/base.py`) is a frozen dataclass `(catalyst, severity, subject, body)` with severity validated against `("LOG", "MED", "HIGH", "CRITICAL")`.

### Shared infrastructure (`lib/`)

- `lib/edgar.py` — SEC EDGAR client (requires `SEC_USER_AGENT`)
- `lib/rss.py` — feedparser wrapper, idempotent on `(feed_url, GUID)` with 30-day TTL
- `lib/xbrl.py` — XBRL facts pull for hyperscaler capex/OCF/FCF (C4)
- `lib/grid_queues.py` — PJM/CAISO interconnection queue XLSX parsers (C5)
- `lib/eia.py`, `lib/fred.py` — Henry Hub & macro data (C5)
- `lib/prices.py` — yfinance wrapper with **6-hour TTL cache** keyed in the `c2_price_check` table (yfinance throttles hard)
- `lib/state.py` — SQLite layer; tables include `c4_xbrl`, `c5_queues`, `llm_cache`, dedup tables
- `lib/notify.py` — Gmail SMTP send + alert dedup + persistence. **SHA-256 over `(subject, body[:500])` with 7-day TTL** prevents repeat emails AND prevents duplicate `alerts` rows. Every non-deduped alert is INSERTed into the `alerts` table regardless of whether SMTP fired. Set `CATALYST_EMAIL_DISABLE=c3,c5` (CSV) to silence specific catalysts' emails while keeping their rows in DB. Header `X-Catalyst-Severity:` still set.
- `lib/thresholds.py` — numeric thresholds (110% capex/OCF, $5/MMBtu Henry Hub, etc.). When tuning email volume, change here rather than in catalyst modules.
- `lib/explanations.py` — `_REGISTRY` of static English "What this means / Why it matters" templates keyed by `(catalyst, signal_kind)`. `append_context()` is the entry point that catalysts call; it bridges to the LLM layer when enabled.
- `lib/llm.py` — invokes local `claude` CLI in headless mode (`claude -p ... --output-format json`) for bilingual EN/中文 explanations. Cache key includes `_PROMPT_VERSION` — **bumping that constant invalidates every cached explanation**. Designed to never break alerting: any failure logs `llm.fallback reason=...` and returns `None`, caller uses static template.
- `lib/log.py` — `get_logger(__name__)`; auto-attaches stack traces in `except` blocks. `LOG_LEVEL` env var controls level (default `INFO`).

### Transition semantics — critical for C4/C5

C4 and C5 numeric alerts fire on **transitions, not on persistent state**. C4 ratio-cross requires prior quarter < 110% and current ≥ 110%; FCF-negative requires prior ≥ 0 and current < 0. C5 MW-drop / new-withdrawals require a prior snapshot.

**Consequence:** the first scan against a fresh `state/tracker.sqlite` is intentionally quiet — it establishes baselines in `c4_xbrl` / `c5_queues`. When writing tests or debugging silence, check whether the prior row exists.

Dedup is per-`(signal_kind, ticker, period)` on top of the 7-day subject/body hash, so a one-time cross emits exactly one email forever (until the database is wiped).

### Cron wrapper (`bin/run_catalyst.sh`)

After `python -m catalysts.<module>` and `scripts/build_dashboard.py`, the wrapper **commits and pushes** `state/tracker.sqlite` + `docs/index.html` + `docs/thresholds.html` + `docs/data/status.json` to `origin/main` with `pull --rebase` retries (the five catalysts cron-fire 6 minutes apart but races still happen). Commits are authored `catalyst-bot <bot@openclaw.local>`; recent `state: ...` commits in `git log` are from cron, not human edits — don't revert them. `tests.yml` uses `paths-ignore` so these state commits don't burn CI.

### LLM explanation path

Activated by `CATALYST_LLM_ENABLED=1`. Disabled by default in tests and dry-runs against a fresh DB unless the env var is set. The full flow (cache → CLI subprocess → JSON envelope parse → 30-day cache write) is documented in README "LLM explanation path" — when changing the prompt schema, bump `_PROMPT_VERSION` in `lib/llm.py` and re-run `scripts/llm_smoke.py`.

GitHub Actions cannot use this path (ephemeral runners can't hold the claude.ai session); the `api` backend in `lib/llm.py` is a stub for an eventual Anthropic-SDK fallback.

### Tests

`tests/` is plain pytest. `tests/fixtures/` holds canary EDGAR/RSS/XBRL snapshots — when changing regex anchors in `lib/thresholds.py` or in a catalyst module, keep the canaries green. `responses` library is used to mock HTTP. There are no integration tests against live SEC/EDGAR/yfinance.

## Source spec

Thresholds and verbatim regex anchors live in `docs/source-spec.md` (§3 and §10). Implementation plans for each catalyst and the LLM layer live in `docs/superpowers/plans/`.

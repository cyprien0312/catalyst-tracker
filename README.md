# catalyst-tracker

AI Infrastructure Bubble-Stress catalyst tracker. Monitors five distinct
signals across SEC filings, news feeds, XBRL financial data, and ISO
interconnection-queue snapshots, and emails alerts via Gmail SMTP.

The dashboard publishes to GitHub Pages from `/docs/`. See
`docs/source-spec.md` for the design document and
`docs/superpowers/plans/` for the step-by-step implementation plans.

## Contents

- [Catalysts](#catalysts) — what is monitored
- [Production deployment](#production-deployment) — current setup: local cron on a single host
- [Local development](#local-development) — venv, tests, dry-run
- [Email alerts](#email-alerts) — subjects, severity tiers, body format
- [Architecture notes](#architecture-notes) — dedup, transitions, cadence, caches
- [Alternative deployment: GitHub Actions](#alternative-deployment-github-actions) — kept as fallback
- [Source spec](#source-spec)

## Catalysts

| ID | Signal | Module |
|---|---|---|
| C1 | GPU depreciation useful-life changes | `catalysts/c1_depreciation.py` |
| C2 | Neocloud distress (going-concern / 8-K items / price crash) | `catalysts/c2_neoclouds.py` |
| C3 | OpenAI financial stress (news + MSFT filings) | `catalysts/c3_openai.py` |
| C4 | Hyperscaler capex/OCF stress (XBRL TTM) | `catalysts/c4_capex.py` |
| C5 | Grid bottlenecks (PJM / CAISO queues, Henry Hub) | `catalysts/c5_grid.py` |

Each catalyst is a standalone module under `catalysts/` with the same shape
(`run()` plus a `__main__` block taking `--dry-run`). Shared infrastructure
lives in `lib/` (EDGAR client, RSS fetcher, XBRL, notify, dedup state, LLM
explanation layer).

## Production deployment

The production deployment runs **on a single Ubuntu host** under user cron.
GitHub Actions schedules are disabled — see
[Alternative deployment](#alternative-deployment-github-actions) for why and
how to re-enable.

### Why a single host instead of GitHub Actions

- Reusing a long-lived `claude` CLI session (`lib/llm.py`) for free LLM
  explanations. Re-authenticating headless on GH Actions is painful.
- Lower cron drift than GH Actions (10–30 min in practice → seconds locally).
- Single source of truth for state — no concurrent writer races.

### Prerequisites on the host

- Ubuntu 22.04+ (or any Linux with cron, Python 3.11+, Node 18+)
- Python 3.11 (we use venv; the system default can be newer)
- `claude` CLI installed and logged in (`claude` → follow the OAuth flow once)
- A writable git credential for `origin` (HTTPS token in `~/.git-credentials`
  or an SSH deploy key — needed so cron can push state back to GitHub)

### Setup

```bash
# 1. Clone next to your home
cd ~ && git clone https://github.com/cyprien0312/catalyst-tracker.git
cd catalyst-tracker

# 2. venv + deps
python3.11 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

# 3. Secrets — write ~/.catalyst.env (outside the repo!), chmod 600
cat > ~/.catalyst.env <<'EOF'
SEC_USER_AGENT="Your Name your-email@example.com"
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
ALERT_TO=you@gmail.com
CATALYST_LLM_ENABLED=1
CATALYST_LLM_SLEEP_AFTER=2
CATALYST_LLM_TIMEOUT=30
CATALYST_LLM_CLAUDE_BIN=/path/to/claude
LOG_LEVEL=INFO
# Optional — only used by C5:
# EIA_API_KEY=
# FRED_API_KEY=
EOF
chmod 600 ~/.catalyst.env
```

### Smoke tests (run before installing cron)

```bash
set -a; source ~/.catalyst.env; set +a

# (a) Verify the LLM CLI path returns a clean JSON envelope
.venv/bin/python scripts/llm_smoke.py
# expect: "OK: llm smoke passed (...)"

# (b) Verify Gmail SMTP credentials
.venv/bin/python scripts/test_alert.py
# expect: "sent" and an email in your inbox

# (c) Dry-run a catalyst end-to-end
.venv/bin/python -m catalysts.c3_openai --dry-run
```

### Install cron

The repo ships a wrapper at `bin/run_catalyst.sh` that sources `~/.catalyst.env`,
activates the venv, fixes `PATH` for cron, runs the catalyst + dashboard, and
commits/pushes `state/` + `docs/` back to `origin/main` (with rebase retries
in case two catalysts race).

```bash
crontab -e
```

Add staggered entries — each catalyst runs on a 30-minute cadence, offset by
6 minutes so they never overlap:

```cron
PATH=/home/YOU/.hermes/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

2,32  * * * * /home/YOU/catalyst-tracker/bin/run_catalyst.sh c1_depreciation
8,38  * * * * /home/YOU/catalyst-tracker/bin/run_catalyst.sh c2_neoclouds
14,44 * * * * /home/YOU/catalyst-tracker/bin/run_catalyst.sh c3_openai
20,50 * * * * /home/YOU/catalyst-tracker/bin/run_catalyst.sh c4_capex
26,56 * * * * /home/YOU/catalyst-tracker/bin/run_catalyst.sh c5_grid
```

Replace `YOU` with your username. Note: cron uses the **host's local timezone**,
not UTC. Adjust the original UTC schedules in `.github/workflows/catalyst*.yml`
if you want different cadence per catalyst.

### Observability

- Per-catalyst logs: `~/catalyst-tracker/logs/<module>.log` (gitignored)
- LLM hit/miss/fallback events: `grep "llm\." logs/*.log`
- Cron firings: `grep CRON /var/log/syslog | grep run_catalyst`
- State pushes: `git log --oneline` (commits authored by `catalyst-bot`)
- Live dashboard: `https://<your-gh-user>.github.io/catalyst-tracker/`

### What the wrapper commits

After each run, `bin/run_catalyst.sh` adds these files to a single commit and
pushes (with `pull --rebase` retries):

- `state/tracker.sqlite` — dedup + transition state
- `docs/index.html` and `docs/thresholds.html` — rebuilt dashboard shell
- `docs/data/status.json` — table counts + latest XBRL rows the dashboard reads

## Local development

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -v
```

Run a single catalyst in dry-run (no email):

```bash
export SEC_USER_AGENT="catalyst-tracker you@example.com"
python -m catalysts.c1_depreciation --dry-run
python -m catalysts.c2_neoclouds --dry-run --no-prices
python -m catalysts.c3_openai --dry-run
python -m catalysts.c4_capex --dry-run
python -m catalysts.c5_grid --dry-run
```

Available CLI flags per module:
- All: `--dry-run` (print alerts instead of emailing)
- C2: `--no-prices` (skip yfinance crash detector)
- C3: `--no-edgar` (RSS feeds only — skip MSFT filings scan)
- C5: `--skip-iso` (skip live PJM/CAISO XLSX downloads — useful when SSL fails locally)

Diagnostics go through `lib/log.py` (`lib.log.get_logger(__name__)`). Stack
traces are attached automatically when logging from an `except` block.
Adjust verbosity via env var:

```bash
LOG_LEVEL=DEBUG python -m catalysts.c3_openai --dry-run
LOG_LEVEL=WARNING python -m catalysts.c5_grid
```

Default level is `INFO`. The end-of-run summary line (`c3: 4 alert(s) emailed`)
prints to stdout, not the logger — intentional.

### Backfill (one-time seed)

```bash
python scripts/backfill.py --dry-run
```

### Dashboard

```bash
python scripts/build_dashboard.py   # writes docs/index.html
```

## Email alerts

Every alert lands in `ALERT_TO` with `From: GMAIL_USER`. Subjects are prefixed
`[C{N}-{SEVERITY}]` so you can build Gmail filters. The header
`X-Catalyst-Severity: CRITICAL|HIGH|MED|LOG` is also set for routing.

### Severity tiers

| Tier | When | Suggested action |
|---|---|---|
| `CRITICAL` | Hard distress signal (going-concern, 8-K item 2.04/4.02/1.03, OpenAI default/bond, covenant breach) | Investigate same day |
| `HIGH` | Strong leading indicator (capex/OCF cross, FCF negative, stock crash, useful-life shortening) | Investigate within a day or two |
| `MED` | Soft signal (Henry Hub stress, queue MW drop, generic Sarah Friar mention) | Skim; correlate with other tiers |
| `LOG` | Tracked but not alert-worthy on its own | No action |

### Subject formats

| Catalyst | Example subject | What it means |
|---|---|---|
| **C1** | `[C1-HIGH] AMZN 10-K: depreciation language change detected` | A regex hit in a freshly-filed 10-K/10-Q for a hyperscaler |
| **C2 (filing)** | `[C2-CRITICAL] APLD 10-Q: distress language detected` | Going-concern / covenant / material-adverse language in a neocloud filing |
| **C2 (8-K)** | `[C2-CRITICAL] CRWV 8-K: distress item(s) 2.04` | A neocloud filed an 8-K item 2.04 / 4.02 / 1.03 |
| **C2 (price)** | `[C2-HIGH] IREN: crash -18.5% on 4.2x volume` | Single-session drop ≥15% on volume ≥3× 20-day avg |
| **C3 (news)** | `[C3-CRITICAL] OpenAI bond prospectus filed — Reuters` | RSS item where an OpenAI mention is within 120 chars of a tier token |
| **C3 (MSFT)** | `[C3-CRITICAL] MSFT 10-K: OpenAI critical-tier mention` | A new MSFT 10-K/10-Q has an OpenAI mention near a CRITICAL token |
| **C4 (cross)** | `[C4-HIGH] MSFT: TTM Capex/OCF crossed 112% (was 89%)` | Hyperscaler's TTM ratio crossed 110% upward this quarter |
| **C4 (jump)** | `[C4-MED] META: Capex/OCF jumped 17pp` | ≥15-percentage-point QoQ jump in the ratio |
| **C4 (FCF)** | `[C4-HIGH] ORCL: TTM FCF turned negative (-30.0B as of 2026-02-28)` | TTM Free Cash Flow went below zero |
| **C5 (MW)** | `[C5-MED] PJM: queue MW down 6.3% vs 2026-04-12` | Interconnection-queue total dropped ≥5% vs prior snapshot |
| **C5 (withdraw)** | `[C5-HIGH] PJM: 7 new withdrawals vs 2026-04-12` | ≥5 new withdrawn projects ≥100 MW since last snapshot |
| **C5 (Henry Hub)** | `[C5-MED] Henry Hub 12mo strip avg $5.18/MMBtu ≥ $5.00` | EIA 12-month gas-futures strip crossed the stress line |
| **OPS test** | `[OPS-TEST] catalyst-tracker SMTP smoke` | Manual test via `scripts/test_alert.py` |

### Body

Each body includes (when applicable): ticker, form, filed date, accession
number, direct EDGAR URL, and the regex-matched snippet (±240 chars) so you
can confirm the signal in one click.

**Every alert ends with a "What this means / Why it matters" section** —
plain-English context for the signal. By default these come from
`lib/explanations.py`, indexed by `(catalyst, signal_kind)`. When
`CATALYST_LLM_ENABLED=1` is set, `lib/llm.py` rewrites them on the fly via the
local `claude` CLI for catalyst-specific phrasing. Misses and fallbacks are
logged with `llm.miss` / `llm.fallback`.

Example tail of a C4 FCF-negative alert:

```
────────────────────────────────────────────────────────────
What this means:
A hyperscaler's trailing-twelve-month free cash flow turned from
non-negative to negative.

Why it matters:
Hyperscalers historically generated massive FCF — that's how the AI capex
was supposed to be paid for. When TTM FCF goes negative, the implicit
funding source switches to debt or balance sheet drawdown. Bank of America
projected hyperscalers would spend ~94% of operating cash flow on capex in
2026. Crossing zero on FCF means capex now exceeds *all* operating cash —
they're pre-funding via debt.
```

### Tuning email volume

- Silence a tier: comment the tier loop in `c3_openai.classify()` or raise
  the threshold in `lib/thresholds.py`.
- Adjust dedup window: `DEDUP_TTL_SECONDS` in `lib/notify.py`.
- Route by severity: Gmail filter on `X-Catalyst-Severity: CRITICAL`
  forwarding to your phone.

## Architecture notes

### Transitions vs. state — when alerts fire

For C4 and the planned C2 numeric triggers, alerts fire on **transitions**,
not on persistent state:

- **C4 ratio cross**: fires only when the previous quarter's TTM Capex/OCF
  was *below* 110% and the current quarter is *at or above* 110%. A company
  at 160% for three years alerts exactly once (when it first crossed), then
  silent until it drops below and re-crosses.
- **C4 FCF turning negative**: fires only when the previous TTM FCF was ≥ 0
  and the current is < 0. Long-standing negative-FCF companies don't alert.
- **C5 ISO MW drop / withdrawals**: requires a prior snapshot. First run for
  a given ISO establishes the baseline.

Consequence: **the first scan of a fresh database is intentionally quiet** —
baseline gets established, then real signals from there. Prior values live
in `c4_xbrl` (`fcf_ttm`, `ratio`) and `c5_queues`; inspect via:

```bash
sqlite3 state/tracker.sqlite ".schema c4_xbrl"
```

### Dedup — no spam

`lib/notify.py` SHA-256-hashes `(subject, body[:500])` and stores it for
**7 days**. Same alert won't re-fire in that window even if the catalyst sees
it on every run. Per-source idempotency is also enforced:

- SEC filings: dedup by accession number (immutable)
- RSS items: dedup by `(feed_url, GUID)` with 30-day TTL
- C4/C5 numeric crosses: dedup by `(signal_kind, ticker, period)`

A "MSFT Capex/OCF crossed 110%" event sends exactly one email even if the
workflow runs daily forever afterwards.

### yfinance price-crash cache (C2)

C2's stock-crash detector hits yfinance, which throttles aggressively.
`lib/prices.py:stock_crash_cached` wraps the check with a **6-hour TTL cache**
via the `c2_price_check` state table. C2 fires hourly during market hours but
yfinance is queried at most once every 6 hours per ticker.

### Cadence (when alerts might land)

| Catalyst | Schedule (host local time) | Typical earliest news from |
|---|---|---|
| C1 | 2× per hour | Quarterly earnings windows (Feb, May, Aug, Nov) |
| C2 | 2× per hour | Any business hour |
| C3 | 2× per hour, 24/7 | Any time — news-driven |
| C4 | 2× per hour | Post-earnings days |
| C5 | 2× per hour, monthly first-Friday for ERCOT | Mostly slow-moving |

The cron in `bin/run_catalyst.sh` runs every catalyst every 30 minutes. Real
news cadence is dominated by source frequency (earnings filings, RSS feed
update rates), not by us.

### LLM explanation path

When `CATALYST_LLM_ENABLED=1`:

1. `lib/explanations.py` builds the static `Explanation` for `(catalyst, signal_kind)`.
2. `lib/llm.summarize_explanation()` calls the local `claude` CLI binary at
   `CATALYST_LLM_CLAUDE_BIN` (default: first `claude` on PATH).
3. Output is a `{"what":..., "why":...}` JSON envelope which replaces the
   static text in the email body.
4. Failures (CLI missing, parse error, timeout) are logged as `llm.fallback
   reason=...` and the static text is used instead — alerts never block on LLM.

The smoke probe at `scripts/llm_smoke.py` verifies the CLI envelope shape
without sending real alerts.

## Alternative deployment: GitHub Actions

The five `catalystN_*.yml` workflows in `.github/workflows/` are configured
for GH Actions but their `schedule:` blocks are **commented out** — the
primary deployment is local cron (see above). `workflow_dispatch:` is kept
so you can still trigger any catalyst manually from the Actions tab.

To re-enable scheduled GH Actions:

1. Uncomment the `schedule:` lines in each `catalystN_*.yml` (and
   `keepalive.yml` if you want the 60-day cron-disable ping).
2. Add repo Secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_TO`,
   `SEC_USER_AGENT`, `EIA_API_KEY` (optional), `FRED_API_KEY` (optional).
3. Enable GitHub Pages: Settings → Pages → Source = `main`, folder `/docs`.

The LLM explanation path (`CATALYST_LLM_ENABLED`) is **not** wired into the
workflows — GH Actions would need to install and authenticate the `claude`
CLI on every run, which isn't worth it. Without that env var the catalysts
fall back to `lib/explanations.py` static text.

## Source spec

The threshold tables and verbatim regex anchors live in `docs/source-spec.md`
(sections §3 and §10). Any regex change should keep the canary tests in
`tests/fixtures/` matching.

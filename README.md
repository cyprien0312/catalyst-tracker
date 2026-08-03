# catalyst-tracker

AI Infrastructure Bubble-Stress catalyst tracker. Monitors nine distinct
signals across SEC filings, news feeds, XBRL financial data, and ISO
interconnection-queue snapshots, and emails alerts via the Resend HTTP API.

The dashboard publishes to GitHub Pages from `/docs/`. See
`docs/source-spec.md` for the design document and
`docs/superpowers/plans/` for the step-by-step implementation plans.

## Contents

- [Catalysts](#catalysts) — what is monitored
- [Production deployment](#production-deployment) — current setup: local cron on a single host
- [Local development](#local-development) — venv, tests, dry-run
- [Email alerts](#email-alerts) — subjects, severity tiers, body format
- [Daily digest](#daily-digest) — priority-ordered heartbeat + FOCUS analysis
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
| C6 | Memory/storage price stress (DRAM/NAND/HBM/SSD/HDD news) | `catalysts/c6_memory.py` |
| C7 | Credit market stress (IG/HY OAS widening, FRED) | `catalysts/c7_credit.py` |
| C8 | Macro triggers (CPI + core PCE YoY hot / re-accelerating, FRED) | `catalysts/c8_macro.py` |
| C9 | Crypto cycle top (BTC Mayer Multiple, Pi Cycle Top) | `catalysts/c9_crypto.py` |
| C10 | Liquidity tightening (broad USD index surge, 10y real-yield spike/stress, FRED) | `catalysts/c10_liquidity.py` |

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

# (b) Verify Resend credentials
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
5,35  * * * * /home/YOU/catalyst-tracker/bin/run_catalyst.sh c6_memory
11,41 * * * * /home/YOU/catalyst-tracker/bin/run_catalyst.sh c7_credit
17    7 * * * /home/YOU/catalyst-tracker/bin/run_catalyst.sh c8_macro
23    8 * * * /home/YOU/catalyst-tracker/bin/run_catalyst.sh c9_crypto

# Daily digest e-mail (priority-ordered heartbeat across all 9 catalysts)
0     9 * * * /home/YOU/catalyst-tracker/bin/send_daily_report.sh
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
python -m catalysts.c6_memory --dry-run
python -m catalysts.c7_credit --dry-run   # keyless FRED CSV
python -m catalysts.c8_macro --dry-run    # keyless FRED CSV
python -m catalysts.c9_crypto --dry-run   # CoinGecko public API
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

**Every alert ends with a "What this means / Why it matters" section.** By
default these come from the static template registry in `lib/explanations.py`,
indexed by `(catalyst, signal_kind)`. When `CATALYST_LLM_ENABLED=1` is set,
`lib/llm.py` replaces them with **bilingual (English + 简体中文)** LLM-generated
explanations that cite the specific ticker / numbers / filing snippet for that
alert. Static fallback stays English-only. Call paths are logged as
`llm.hit` (cache) / `llm.miss` (fresh CLI call) / `llm.fallback reason=…`.

Example tail of a C4 RATIO_CROSS alert with the LLM path on:

```
────────────────────────────────────────────────────────────
What this means:
META's capex-to-operating-cash-flow ratio crossed above the 110%
threshold, hitting 113.4% in 2026-Q1 versus 96.8% prior
($71.2B capex on $62.8B OCF).

内容:
META 资本开支对经营现金流的比率突破 110% 阈值，2026-Q1 达到 113.4%，
上一期为 96.8%（capex $71.2B / OCF $62.8B）。

Why it matters:
Capex is now outrunning the cash the business generates, so incremental
AI buildout is being funded externally rather than from operations.
Crossing 100% — and now the 110% stress line — marks the point where the
spend cycle stops being self-financing, a classic late-cycle capex signal.

影响:
资本开支已经跑赢业务自身产生的现金流，意味着增量 AI 建设要靠外部融资
而非经营现金支撑。突破 100%、再到 110% 压力线，标志着支出周期不再
自给自足，是经典的周期晚期 capex 信号。
```

### Tuning email volume

- **Mute a whole catalyst's emails**: add `CATALYST_EMAIL_DISABLE=c3` (CSV) to
  `~/.catalyst.env`. The alert still lands in the `alerts` table and shows up
  in the dashboard, but no email is sent. Useful when one catalyst is too
  chatty (C3 in particular hits frequently because RSS feeds update fast).
- **Email only above a severity floor** (preferred over a blanket mute):
  `CATALYST_EMAIL_MIN_SEVERITY=c6:HIGH,c8:HIGH,c3:HIGH` (CSV of `tag:floor`).
  For that catalyst, only alerts at or above the floor are e-mailed; quieter
  ones still persist to the DB and dashboard. The floor takes precedence over
  `CATALYST_EMAIL_DISABLE` for the same tag. This keeps the noisy MED-tier
  catalysts (C3 IPO chatter, C6 froth, C8 monthly CPI) out of your inbox while
  still pinging you on a genuine HIGH/CRITICAL. The agreed loud-vs-floored split:
  loud (all severities) = the fuses C7/C2 and hard-data C4/C1; floored to HIGH =
  C8/C10/C6/C3/C5/C9.
- Silence a tier: comment the tier loop in `c3_openai.classify()` or raise
  the threshold in `lib/thresholds.py`.
- Adjust dedup window: `DEDUP_TTL_SECONDS` in `lib/notify.py`.
- Route by severity: Gmail filter on `X-Catalyst-Severity: CRITICAL`
  forwarding to your phone.

### Dashboard alert viewer

The GitHub Pages dashboard at `https://<your-gh-user>.github.io/catalyst-tracker/`
now renders the last 200 rows of the `alerts` table with catalyst/severity
filters. Read-state is tracked in browser `localStorage` (per-device, not
synced across phone/laptop). "Reset read state" wipes the local set.

## Daily digest

A once-a-day heartbeat e-mail summarising all ten catalysts in priority order
— sent even when nothing fired, so absence of an alert is informative too.

```bash
python scripts/daily_report.py             # send now
python scripts/daily_report.py --dry-run   # print the text body
python scripts/daily_report.py --html-out /tmp/d.html  # also dump the HTML
bin/send_daily_report.sh                    # cron wrapper (sources env, logs)
```

What it contains, top to bottom:

- **Status pills** — count of 🔴 firing / 🟡 watch / 🟢 quiet across the ten.
- **★ FOCUS / 今日重点** — an analytical read of the single most important thing
  today: the highest-priority *firing* signal, its live numbers, the standing
  cross-signal thesis, and what would confirm/escalate it. Written by the LLM
  (`llm.freeform`, Opus by default) when the CLI is available; falls back to a
  rule-based analysis (`_analytical_focus`, with per-signal baked-in context) so
  the digest never depends on the LLM being up. Bilingual EN/中文.
- **Priority-grouped cards** — C7→C2→C4→C1→C8→C10→C6→C3→C5→C9 in four tiers
  (fuses → hard data → background → lagging), each with a status badge and the
  live gauge / 7-day roll-up.
- **Notable (HIGH+) last 7d** — deduped HIGH/CRITICAL subjects only, cutting
  through MED noise (e.g. C3's IPO-headline flood).

The numeric gauges (C7 spreads, C8 CPI+PCE, C10 USD/real-yield, C9 Mayer) are **re-fetched live** each
run, so the digest is current regardless of when the per-catalyst cron last ran;
C4 reads the latest `c4_xbrl` snapshot; the event-driven catalysts roll up the
`alerts` table. The e-mail is multipart (HTML body + plain-text fallback) and is
sent independently of the per-alert path — no dedup, it goes out every day.
Priority order and the loud-vs-floored e-mail split are documented under
[Tuning email volume](#tuning-email-volume).

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
| C6 | 2× per hour | Any time — news-driven (TrendForce/DigiTimes) |
| C7 | 2× per hour | Daily FRED update (credit spreads) |
| C8 | Daily 07:17 | Monthly CPI + core PCE prints |
| C9 | Daily 08:23 | Daily BTC close |
| C10 | Daily 08:29 | Daily FRED update (USD index, real yield) |
| Daily digest | Daily 09:00 | Heartbeat — always sends |

C1–C7 run every 30 minutes; C8/C9/C10 are daily (their sources are monthly/daily).
Real news cadence is dominated by source frequency (earnings filings, RSS feed
update rates), not by us.

### LLM explanation path

`lib/llm.py` calls the local `claude` CLI in headless mode
(`claude -p ... --output-format json`) so it works against the user's
claude.ai subscription with no API key. Designed to **never break alerting** —
every external dependency is wrapped, any failure returns `None` and the caller
silently falls back to the static `_REGISTRY` in `lib/explanations.py`.

**Flow per alert** (when `CATALYST_LLM_ENABLED=1`):

1. `append_context(body, catalyst, signal_kind, ticker=…, snippet=…, numbers=…)`
   in `lib/explanations.py` invokes `llm.summarize_explanation`.
2. `summarize_explanation` computes a cache key including the prompt version,
   model tag, catalyst, signal kind, ticker, `sha256(snippet[:4000])`, and the
   `numbers` dict. Hit → return cached `Explanation` (log `llm.hit`).
3. Miss → build prompt with system rules, two few-shot examples (C1 AMZN +
   C4 META, both bilingual), and the alert-specific input as JSON.
4. `subprocess.run(["claude", "-p", prompt, "--model", <model>, "--output-format", "json"])`
   with per-call timeout. Parse envelope (`{is_error, subtype, result}`), then extract
   the inner `{what, why, what_zh, why_zh}` JSON (tolerates ```json fences).
   The `--model` is passed explicitly (default `claude-opus-4-8`) because the CLI's
   own default (Fable 5) returns `is_error="Claude Fable 5 is currently unavailable"`
   in some regions (e.g. AU), which would silently force the static-template fallback.
5. Cache the result with 30-day TTL in the `llm_cache` table of
   `state/tracker.sqlite`. Sleep 2s after a successful fresh call (rate-limit
   courtesy). Log `llm.miss`.
6. Any failure → log `llm.fallback reason=<branch>` and return `None`; the
   caller renders the English-only static template.

**Context passed by each catalyst:**

| Catalyst | Signal kinds | Context passed to LLM |
|---|---|---|
| C1 | depreciation patterns | `ticker` + concatenated `hits[*].snippet` |
| C2 | 8-K items, filing scan, stock crash | `ticker` + items/snippet/crash numbers |
| C3 | RSS HIGH/MED/CRITICAL, MSFT filings | `snippet=title+summary`; MSFT path adds `ticker=MSFT` + filing text |
| C4 | FCF_NEGATIVE, RATIO_CROSS, RATIO_JUMP | `ticker` + `numbers` dict (capex, OCF, FCF, ratio, period) |
| C5 | MW_DROP, NEW_WITHDRAWALS, HENRY_HUB_STRESS | `numbers` dict (ISO/MW/withdrawals/strip values); no ticker |
| C6 | price reversal/surge/order-unwind | `snippet=title+summary` |
| C7 | SPREAD_WIDENING, SPREAD_STRESS | `numbers` dict (series, current_bp, low_bp, widened_bp) |
| C8 | CPI_HOT, CPI_REACCEL, PCE_HOT, PCE_REACCEL | `numbers` dict (yoy_pct, threshold, month) |
| C9 | MAYER_HOT, PI_CYCLE_TOP | `numbers` dict (mayer, price, sma200 / sma111, sma350x2) |
| C10 | DOLLAR_SURGE, REAL_YIELD_SPIKE, REAL_YIELD_STRESS | `numbers` dict (series, current, low/stress_level, rise) |

The **daily digest** uses a separate entry point, `llm.freeform(prompt)`, to
write the FOCUS note (see below) rather than the per-alert `summarize_explanation`
path. Same CLI, same `--model`, same graceful fallback.

**Tunable env vars:**

| Env var | Default | Purpose |
|---|---|---|
| `CATALYST_LLM_ENABLED` | unset | Master switch; must be `"1"` to activate |
| `CATALYST_LLM_BACKEND` | `cli` | `cli` (only one implemented); `api` reserved for future Anthropic-SDK backend |
| `CATALYST_LLM_CLAUDE_BIN` | `which claude` | Override binary path (useful in cron) |
| `CATALYST_LLM_TIMEOUT` | `30` | Per-call subprocess timeout, seconds |
| `CATALYST_LLM_SLEEP_AFTER` | `2` | Seconds to sleep after a successful fresh call; `0` disables |
| `CATALYST_LLM_MODEL` | `claude-opus-4-8` | Passed to `claude --model`; also the cache-key namespace tag. Override if Opus is unavailable or to pin another model. |

The prompt version is bumped (`_PROMPT_VERSION` in `lib/llm.py`) whenever the
system prompt or schema changes, which automatically invalidates all cached
entries without manual purge.

**Smoke test before enabling:** `python scripts/llm_smoke.py` does a real
envelope check + end-to-end probe against a temp DB so it doesn't pollute prod
cache. Run this once after installing/upgrading the `claude` CLI to verify the
envelope shape hasn't changed upstream.

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
workflows — GH Actions runners are ephemeral and can't reuse the local
claude.ai session, so the CLI backend has no way to authenticate. Without that
env var the catalysts fall back to `lib/explanations.py` static English text
(no Chinese in fallback). If you need LLM-augmented alerts from GH Actions,
the path forward is the `api` backend stub in `lib/llm.py` (Anthropic API key
as a repo secret) — see step 7 in
`docs/superpowers/plans/2026-05-14-llm-summarization-layer.md`.

The `tests.yml` workflow uses `paths-ignore` so it doesn't re-run on
state-only commits pushed by the cron host — only actual code changes trigger
CI.

## Source spec

The threshold tables and verbatim regex anchors live in `docs/source-spec.md`
(sections §3 and §10). Any regex change should keep the canary tests in
`tests/fixtures/` matching.

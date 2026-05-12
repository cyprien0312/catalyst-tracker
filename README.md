# catalyst-tracker

AI Infrastructure Bubble-Stress catalyst tracker. Monitors five distinct
signals across SEC filings, news feeds, XBRL financial data, and ISO
interconnection-queue snapshots, and emails alerts via Gmail SMTP.

See `docs/source-spec.md` for the design document, and
`docs/superpowers/plans/` for the step-by-step implementation plans.

## Catalysts

| ID | Signal | Module |
|---|---|---|
| C1 | GPU depreciation useful-life changes | `catalysts/c1_depreciation.py` |
| C2 | Neocloud distress (going-concern / 8-K items / price crash) | `catalysts/c2_neoclouds.py` |
| C3 | OpenAI financial stress (news + MSFT filings) | `catalysts/c3_openai.py` |
| C4 | Hyperscaler capex/OCF stress (XBRL TTM) | `catalysts/c4_capex.py` |
| C5 | Grid bottlenecks (PJM / CAISO queues, Henry Hub) | `catalysts/c5_grid.py` |

## Local dev

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -v
```

## Test the SMTP alert path

```bash
export GMAIL_USER=you@gmail.com
export GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx   # 16 chars, no spaces
export ALERT_TO=you@gmail.com
python scripts/test_alert.py
```

## Run a single catalyst (dry-run)

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

## Logging

All diagnostics route through `lib/log.py` (`lib.log.get_logger(__name__)`).
Stack traces are included automatically when logged from an `except` block.

Adjust verbosity via env var:
```bash
LOG_LEVEL=DEBUG python -m catalysts.c3_openai --dry-run
LOG_LEVEL=WARNING python -m catalysts.c5_grid    # quieter in production
```

Default level is `INFO`. The end-of-run summary line (`c3: 4 alert(s) emailed`)
goes to stdout via `print()` — intentional, not a logger message.

## Backfill (one-time seed)

```bash
python scripts/backfill.py --dry-run
```

## Dashboard

```bash
python scripts/build_dashboard.py   # writes docs/index.html
```

## Deploy on GitHub Actions

1. Push this repo to GitHub (public recommended — unlimited Actions minutes).
2. Enable GitHub Pages: Settings → Pages → Source = `main` branch, folder `/docs`.
3. Add Secrets (Settings → Secrets and variables → Actions):
   - `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_TO`
   - `SEC_USER_AGENT` — e.g., `catalyst-tracker you@example.com`
   - `EIA_API_KEY` (optional — for C5 Henry Hub)
   - `FRED_API_KEY` (optional)
4. The five `catalystN_*.yml` workflows run on cron (see `.github/workflows/`).
5. `keepalive.yml` pings weekly to prevent the 60-day cron disable.

## Email alerts — what to expect

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

### Subject formats per catalyst

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

### Email body

Each body includes (when applicable): ticker, form, filed date, accession
number, direct EDGAR URL, and the regex-matched snippet (±240 chars) so you
can confirm the signal in one click.

### Transition vs. state — when alerts fire

For C4 (capex) and the planned C2 numeric triggers, alerts fire on
**transitions**, not on persistent state. Concretely:

- **C4 ratio cross**: fires only when the previous quarter's TTM Capex/OCF was
  *below* 110% and the current quarter is *at or above* 110%. A company that
  has been at 160% for three years will alert exactly once (when it first
  crossed), then never again until it drops below and re-crosses.
- **C4 FCF turning negative**: fires only when the previous TTM FCF was
  ≥ 0 and the current is < 0. Long-standing negative-FCF companies do not
  alert on every scan.
- **C5 ISO MW drop / withdrawals**: requires a prior snapshot. First run for a
  given ISO just establishes the baseline.

This means the **first scan of a fresh database is intentionally quiet** —
you'll get the baseline established, then real signals from there.

The prior values live in `c4_xbrl` (`fcf_ttm`, `ratio`) and `c5_queues`. Run
`sqlite3 state/tracker.sqlite ".schema c4_xbrl"` to inspect.

### yfinance price-crash cache (C2)

The C2 stock-crash detector hits yfinance, which throttles aggressively.
`lib/prices.py:stock_crash_cached` wraps the check with a **6-hour TTL cache**
via the `c2_price_check` state table. C2 fires hourly during market hours but
yfinance is queried at most once every 6 hours per ticker.

### Dedup — you will NOT get spam

`lib/notify.py` SHA-256 hashes `(subject, body[:500])` and stores it for
**7 days**. The same alert won't re-fire in that window even if the catalyst
sees it on every scheduled run. Per-source idempotency is also enforced:
- SEC filings dedup by accession number (immutable)
- RSS items dedup by `(feed_url, GUID)` with a 30-day TTL
- C4/C5 numeric crosses dedup by `(signal_kind, ticker, period)`

So a single "MSFT Capex/OCF crossed 110%" event sends exactly one email even
though the workflow runs daily forever afterwards.

### Cadence — when you might wake up to an alert

| Catalyst | Cron (UTC) | Typical earliest news from |
|---|---|---|
| C1 | daily 11:00 | Quarterly earnings windows (Feb, May, Aug, Nov) |
| C2 | hourly during US market hours, weekends light | Any business hour |
| C3 | every 30 min, 24/7 | Any time — news-driven |
| C4 | daily 11:30 | Post-earnings days |
| C5 | daily 10:00, monthly first-Friday for ERCOT | Mostly slow-moving |

GitHub Actions cron drift is 10–30 min in practice. So worst-case C3 latency
on a breaking news item is ~45 min.

### Tuning email volume

- Make a tier silent: comment the tier loop in `c3_openai.classify()` or set
  the threshold in `lib/thresholds.py` higher.
- Change dedup window: `DEDUP_TTL_SECONDS` in `lib/notify.py`.
- Route by severity: add Gmail filters on `X-Catalyst-Severity: CRITICAL`
  forwarding to your phone.

## Source-spec note

The threshold tables and verbatim regex anchors live in `docs/source-spec.md`
(sections §3 and §10). Any regex change should keep the canary tests in
`tests/fixtures/` matching.

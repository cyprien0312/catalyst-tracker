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

## Source-spec note

The threshold tables and verbatim regex anchors live in `docs/source-spec.md`
(sections §3 and §10). Any regex change should keep the canary tests in
`tests/fixtures/` matching.

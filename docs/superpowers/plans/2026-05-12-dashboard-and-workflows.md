# Dashboard + GitHub Actions Workflows — Implementation Plan

**Prereq:** Catalysts 1–5 complete.

**Goal:** (a) Generate a static HTML dashboard from SQLite state. (b) Add GitHub Actions workflows per source §4.

## Files
- Create: `scripts/build_dashboard.py`, `scripts/backfill.py`, `docs/index.html.j2`, `docs/index.html` (generated), `docs/data/status.json` (generated)
- Create: `.github/workflows/catalyst1_depreciation.yml`, `catalyst2_neoclouds.yml`, `catalyst3_openai.yml`, `catalyst4_capex.yml`, `catalyst5_grid.yml`, `dashboard_build.yml`, `keepalive.yml`

## Dashboard

`scripts/build_dashboard.py` reads `state/tracker.sqlite` and emits:
- `docs/data/status.json` — summary blob (per-catalyst last-run, alert counts).
- `docs/index.html` — Jinja2-rendered minimal page with a status table and a recent-alerts table. No Chart.js for now (KISS); a `<table>` per catalyst is enough.

## Workflows

Common structure:
```yaml
on:
  schedule: [ {cron: "..."} ]
  workflow_dispatch:
permissions:
  contents: write
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install -r requirements.txt
      - env: { SEC_USER_AGENT: ..., GMAIL_*: ..., ALERT_TO: ..., EIA_API_KEY: ..., FRED_API_KEY: ... }
        run: python -m catalysts.cN_xxx
      - run: python scripts/build_dashboard.py
      - uses: stefanzweifel/git-auto-commit-action@v5
        with:
          file_pattern: state/tracker.sqlite docs/data/status.json docs/index.html
          commit_message: "state: cN run ${{ github.run_id }}"
```

Cadence per source §4. Keepalive workflow pushes a heartbeat weekly to prevent the 60-day disable.

## Tasks
1. `scripts/build_dashboard.py` (Jinja2). Tested by running once locally and asserting `docs/index.html` contains expected substrings.
2. `scripts/backfill.py --catalyst all` — runs each catalyst once.
3. Workflow YAML files — committed but not run from here (require GitHub remote).
4. Update README with deploy instructions.

# Catalyst 4 — Hyperscaler Capex Guidance Cuts — Implementation Plan

**Prereq:** Foundation done.

**Goal:** Detect hyperscaler capex/cash-flow stress via XBRL company-concept API + transcript regex.

**Architecture:** `catalysts/c4_capex.py` + `lib/xbrl.py`. Uses SEC's `companyconcept/CIK{cik}/us-gaap/{concept}.json` for `PaymentsToAcquirePropertyPlantAndEquipment` and `NetCashProvidedByUsedInOperatingActivities`. Compute TTM (last 4 quarterly USD values). Persist into `c4_xbrl` SQLite table. Alert on threshold crossings.

## Files
- Create: `catalysts/c4_capex.py`, `lib/xbrl.py`
- Tests: `tests/test_c4.py`, `tests/test_xbrl.py`, `tests/fixtures/xbrl_msft_capex.json`

## Triggers (source §3-C4)
- TTM capex/OCF crosses ≥110% (vs prior quarter's stored value)
- QoQ jump ≥15 percentage points in capex/OCF
- YoY capex growth decelerates from >50% to <20%
- FCF (=OCF − capex) turns negative TTM
- Transcript regex pack (3 patterns) — transcript scraping is stubbed (Motley Fool layout is volatile); regex pack present, but transcript fetcher returns empty list by default. Wire-up complete; user can plug in transcript source later.

## Tasks
1. `lib/xbrl.py::company_concept(client, cik, concept) -> list[XbrlPoint]` where `XbrlPoint = (period_end, value, fp, fy, accn, form)`. Filter to USD, quarterly (`form` in `10-Q,10-K`), de-duped by `(period_end, fp, fy)`. Uses `EdgarClient._get` for rate-limited fetch.
2. `lib/xbrl.compute_ttm(points, anchor_end)` — sum of 4 most recent quarter-end values ≤ anchor_end.
3. `Catalyst4.run()`:
    - For each hyperscaler, fetch capex + OCF, compute latest TTM ratio and prior-quarter ratio from stored history.
    - Persist new (cik, period_end, capex, ocf, ratio) into `c4_xbrl`.
    - If ratio crosses 110% or jumps 15pp, emit Alert.
    - If FCF negative, emit Alert.
4. CLI + live dry-run.

Tests use fixtures with handcrafted XBRL JSON containing 8 quarters of synthetic data; assertions verify TTM math and trigger logic.

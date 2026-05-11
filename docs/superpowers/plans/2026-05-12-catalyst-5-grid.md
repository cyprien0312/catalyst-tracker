# Catalyst 5 — Grid Bottlenecks — Implementation Plan

**Prereq:** Foundation done.

**Goal:** Detect data-center power constraints via ISO interconnection-queue snapshots (PJM/ERCOT/CAISO) + Henry Hub futures + Google News.

**Architecture:** `catalysts/c5_grid.py` + `lib/grid_queues.py` + `lib/eia.py` + `lib/fred.py`. Daily snapshot of queue MW totals; compare MoM. EIA/FRED keys optional — module gracefully no-ops if `EIA_API_KEY` / `FRED_API_KEY` not set, alert logs to stderr. PJM and CAISO are public XLSX, no key.

## Files
- Create: `catalysts/c5_grid.py`, `lib/grid_queues.py`, `lib/eia.py`, `lib/fred.py`
- Tests: `tests/test_c5.py`, `tests/test_eia.py`, `tests/test_fred.py`, `tests/test_grid_queues.py`
- Fixtures: small fabricated XLSX (built in test via openpyxl) + JSON stubs for EIA/FRED.

## Triggers (source §3-C5)
- PJM queue: ≥5 new "Withdrawn" entries WoW (≥100 MW)
- ERCOT total MW down ≥5% MoM
- CAISO ≥3 suspensions in cycle
- Henry Hub 12-month strip avg ≥ $5.00 OR ≥15% jump in 5 sessions
- Google News RSS hit on the bottleneck query

## Tasks
1. `lib/grid_queues.pjm_active_queue() -> DataFrame` — `requests.get(...)`, `pd.read_excel(BytesIO)`.
2. `lib/grid_queues.caiso_queue() -> DataFrame`.
3. Snapshot helpers: `summarize(df, iso) -> dict(total_mw, count, withdrawn_count)` — schema-defensive (PJM column name is `MW Capacity` or `MW Energy`; we coalesce).
4. `lib/eia.henry_hub_strip(api_key) -> list[float]` — pulls `NG.RNGC1.D`..`NG.RNGC12.D` last value each, returns list.
5. `Catalyst5.run()` — store snapshots in `c5_queues`, compare to previous snapshot, emit alerts. Skip EIA/FRED sections if keys absent.
6. CLI + live dry-run.

## Defensive notes
- ERCOT GIS landing scraping is fragile (HTML structure). Implement minimal "find newest `.xlsx` link in resource page"; if fails, log and skip — do not crash other catalysts.
- All HTTP calls use a shared `User-Agent: catalyst-tracker cyprien0312@gmail.com`.

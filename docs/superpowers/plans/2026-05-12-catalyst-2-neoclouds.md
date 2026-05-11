# Catalyst 2 — Neocloud Distress — Implementation Plan

**Prerequisite:** Foundation + Catalyst 1 plans complete.

**Goal:** Detect distress signals on neocloud watchlist (CRWV, APLD, IREN, NBIS) from (a) 10-Q/10-K language (going-concern, covenants), (b) 8-K items 2.04 / 4.02 / 1.03, (c) stock-price crashes via yfinance, and emit alerts.

**Architecture:** `catalysts/c2_neoclouds.py` subclasses `CatalystBase`. Uses `EdgarClient` for filings + 8-K item parsing (extend client to expose `items`). yfinance for stock price + volume. FINRA bond scraping and Nasdaq short interest are documented but deferred (HTML scraping is fragile — wired up as optional `lib/prices.py` + `lib/finra.py` modules with conservative defaults). Source spec §3-Catalyst2 + §10-C2.

**Tech Stack:** Existing libs + `yfinance`.

## File Structure
- Create: `catalysts/c2_neoclouds.py`, `lib/prices.py`, `lib/finra.py`
- Modify: `lib/edgar.py` — add `items` field to `Filing` and `eight_k_items()` helper (parse from submissions JSON)
- Tests: `tests/test_c2.py`, `tests/test_prices.py`, `tests/fixtures/apld_10q_going_concern.txt`, `tests/fixtures/edgar_submissions_apld.json`

## Trigger Pack (per source spec §3-C2)
| Signal | Regex / threshold | Severity |
|---|---|---|
| Going concern | `substantial\s+doubt[^.]{0,80}going\s+concern` | CRITICAL |
| Covenant breach | `covenant\s+(breach|default|waiver|amendment)` | HIGH |
| Material adverse | `material\s+adverse\s+(change|effect)[^.]{0,80}(liquidity|debt)` | HIGH |
| 8-K item 2.04 / 4.02 / 1.03 | filing has item | CRITICAL |
| Stock crash | 1d close ≤ −15% AND volume ≥ 3× 20d avg | HIGH |

## Tasks

### Task 1 — Extend EdgarClient with 8-K items + add fixture
- [ ] Modify `lib/edgar.py`: add `items: tuple[str,...] = ()` to `Filing`, populate from `rec["items"][i]` if present (8-Ks only). Update `tests/test_edgar.py` if needed.
- [ ] Add `tests/fixtures/edgar_submissions_apld.json` containing one 10-Q (no items) and one 8-K with `items: "2.04,7.01"`.
- [ ] New test: `recent_filings` returns the parsed items tuple.
- [ ] Commit.

### Task 2 — Going-concern fixture + regex tests
- [ ] `tests/fixtures/apld_10q_going_concern.txt` containing the verbatim APLD passage from source spec §3-C2.
- [ ] `tests/test_c2.py::test_going_concern_regex_matches_fixture` — calls `c2.scan_text` (similar shape to c1) and asserts CRITICAL hit.
- [ ] `c2_neoclouds.scan_text` impl with the 3 text patterns above.

### Task 3 — `lib/prices.py` price-crash detector
- [ ] `def stock_crash(ticker: str, fetch=None) -> dict | None`: returns `{close, prior_close, change_pct, volume, avg20, ratio}` if crash criteria met. `fetch` injects yfinance for testability.
- [ ] Test with synthetic pandas DataFrame.

### Task 4 — `Catalyst2.run()` end-to-end
- [ ] Iterate NEOCLOUDS watchlist. For each: scan recent 10-K/10-Q text for the 3 patterns; scan 8-Ks for the 3 trigger items; call `stock_crash`. Emit one Alert per signal.
- [ ] Tests with mocked Edgar + injected fetch.
- [ ] Idempotency via `state.seen("c2_filings", accession)` and `state.seen("c2_crash", f"{ticker}|{date}")`.

### Task 5 — CLI + live dry-run
- [ ] `--dry-run` flag.
- [ ] Live: `SEC_USER_AGENT=... python -m catalysts.c2_neoclouds --dry-run`.
- [ ] Commit state seed.

### Deferred (documented stubs only — fragile HTML scraping):
- `lib/finra.py` — bond price scraper. Returns `None` for now; full impl when needed.
- Nasdaq short-interest scraper — same treatment.

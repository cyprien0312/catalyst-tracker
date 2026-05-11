# Catalyst 3 — OpenAI Financial Stress — Implementation Plan

**Prereq:** Foundation done.

**Goal:** Monitor news RSS feeds + MSFT 10-K/10-Q text for OpenAI distress signals; dedup by GUID + content hash; emit alerts.

**Architecture:** `catalysts/c3_openai.py`. `lib/rss.py` wraps `feedparser` with conditional-GET (etag/last-modified) caching and per-feed dedup. Keyword set + severity tiers from source spec §3-C3. MSFT filing scan reuses `EdgarClient`.

## Files
- Create: `catalysts/c3_openai.py`, `lib/rss.py`
- Tests: `tests/test_c3.py`, `tests/test_rss.py`, `tests/fixtures/sample_feed.xml`

## Severity tiers (source §3-C3)
- CRITICAL: `bond | prospectus | default | covenant | write-down | impair | restructuring` (any one)
- HIGH:     `burn rate | losses | down round | valuation cut | IPO`
- MED:      `Sarah Friar` alone, or bare `revenue` mention

## Tasks
1. `lib/rss.py` — `fetch(feed_url, state) -> list[Entry]`, where `Entry` is dataclass `(guid, title, link, summary, feed_url, published)`. State is used to skip seen GUIDs; etag/last-modified persisted in `seen` table under keys like `rss_etag:{url}`.
2. `tests/test_rss.py` — uses `responses` to serve `sample_feed.xml`; asserts new entries returned first time, none second time, etag captured.
3. `c3_openai.classify(text) -> str | None` — applies severity tiers against text (title + summary).
4. `Catalyst3.run()` — iterates feed URLs (a small, robust default list: Google News query for "OpenAI", Bloomberg Tech, WSJ tech). Each entry: classify, dedup, emit Alert. Also scans MSFT 10-K/10-Q for OpenAI mentions matching CRITICAL tier.
5. CLI + live dry-run.

## Deferred / minimal
- The Information feed is paywalled headlines — included in URL list but flagged with `min_severity=MED`.
- Numeric-extraction (burn rate QoQ) — code structure in place; threshold logic is `# TODO` only if no baseline row present (acceptable per spec since the c3_baselines table is empty by design at first run).

Actually — per the foundation plan, no `TODO` placeholders. Spec wants this implemented. Solution: numeric extraction lives in `c3_openai.extract_metrics(text) -> dict`, logs to `c3_baselines` table (created on demand via `state.connection()`), alerts if the QoQ delta exceeds threshold. For first run, the table is empty → no alert (correct behavior, not a placeholder).

# Catalyst 1 — GPU Depreciation Useful-Life Changes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Prerequisite:** Foundation plan (`2026-05-11-foundation.md`) is complete and `pytest` is green.

**Goal:** Detect new 10-K/10-Q filings from six hyperscaler watchlist companies that change accounting useful-life estimates on servers/networking equipment, and email an alert per match with severity + verbatim snippet.

**Architecture:** New `catalysts/c1_depreciation.py` subclasses `CatalystBase`. For each watchlist CIK, list recent 10-K/10-Q via `EdgarClient.recent_filings`, skip filings whose accession is already in `c1_filings` (SQLite), fetch the filing text via EDGAR, run 8 compiled regexes against the text, emit one `Alert` per filing with hits (max severity wins), persist matched hits as JSON. `--dry-run` flag prints alerts without emailing.

**Tech Stack:** Python 3.11+, `lib/edgar.py`, `lib/state.py`, `lib/notify.py`, regex. Tests use real filing excerpts as fixtures + responses-mocked EDGAR calls.

**Source spec:** `docs/source-spec.md` §3-Catalyst1 and §10-C1.

---

## File Structure

Create:
- `catalysts/c1_depreciation.py` — main catalyst
- `tests/test_c1_regex.py` — regex unit tests against verbatim fixtures + decoys
- `tests/test_c1_run.py` — end-to-end `Catalyst1.run()` with mocked EDGAR
- `tests/fixtures/amzn_2024_10k_excerpt.txt` — verbatim AMZN match text
- `tests/fixtures/meta_2024_10k_excerpt.txt` — verbatim META match text
- `tests/fixtures/decoy_useful_life.txt` — unrelated PP&E text that must NOT match

Modify:
- (none — uses Foundation's `lib/`, `catalysts/base.py`)

---

## Task 1: Verbatim and decoy fixtures

**Files:**
- Create: `tests/fixtures/amzn_2024_10k_excerpt.txt`
- Create: `tests/fixtures/meta_2024_10k_excerpt.txt`
- Create: `tests/fixtures/decoy_useful_life.txt`

These are CI canaries — if a future regex refactor stops matching them, CI fails immediately.

- [ ] **Step 1: Write `tests/fixtures/amzn_2024_10k_excerpt.txt`**

```
We completed our most recent servers and networking equipment useful life study in Q4 2024, and are changing the useful lives of a subset of our servers and networking equipment, effective January 1, 2025, from six years to five years. As a result, we anticipate a decrease in 2025 operating income of approximately $0.7 billion.

We recorded approximately $920 million of accelerated depreciation and related charges for the quarter ended December 31, 2024, related to certain servers and networking equipment.

These two changes above are due to an increased pace of technology development, particularly in the area of artificial intelligence and machine learning.
```

- [ ] **Step 2: Write `tests/fixtures/meta_2024_10k_excerpt.txt`**

```
In January 2025, we completed an assessment of the useful lives of certain servers and network assets, which resulted in an increase in their estimated useful life to 5.5 years, effective beginning fiscal year 2025. This change in accounting estimate for servers and network assets is expected to reduce our full-year 2025 depreciation expense by approximately $2.9 billion.
```

- [ ] **Step 3: Write `tests/fixtures/decoy_useful_life.txt`**

A passage that mentions "useful life" generically with no server/network anchor and no quantitative change — the regex pack must NOT fire:

```
Property and equipment are stated at cost less accumulated depreciation. We review the useful life of our office furniture and leasehold improvements periodically and adjust as appropriate. No changes were made during the year.
```

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/amzn_2024_10k_excerpt.txt tests/fixtures/meta_2024_10k_excerpt.txt tests/fixtures/decoy_useful_life.txt
git commit -m "test(c1): fixture excerpts (AMZN/META verbatim + decoy)"
```

---

## Task 2: Regex pack + unit tests

**Files:**
- Create: `catalysts/c1_depreciation.py` (regex module first; class added in Task 3)
- Test: `tests/test_c1_regex.py`

- [ ] **Step 1: Write `tests/test_c1_regex.py`**

```python
from pathlib import Path
from catalysts.c1_depreciation import scan_text, PATTERNS, MAX_SEVERITY_RANK

FIX = Path(__file__).parent / "fixtures"

def test_pattern_set_has_expected_keys():
    keys = {k for k, _, _ in PATTERNS}
    assert keys == {
        "USEFUL_LIFE_SHORTENED_6_TO_5",
        "USEFUL_LIFE_EXTENDED_4_TO_6",
        "USEFUL_LIFE_STUDY",
        "AMZN_SUBSET_PHRASE",
        "ESTIMATE_CHANGE",
        "META_5_5_YEARS",
        "ACCEL_DEPREC",
        "IMPAIRMENT_PPE",
    }

def test_amzn_excerpt_matches_expected_patterns():
    text = (FIX / "amzn_2024_10k_excerpt.txt").read_text()
    hits = scan_text(text)
    keys = {h["key"] for h in hits}
    # Must catch the headline change and the verbatim subset phrase and the study and accelerated depreciation.
    assert "USEFUL_LIFE_SHORTENED_6_TO_5" in keys
    assert "AMZN_SUBSET_PHRASE" in keys
    assert "USEFUL_LIFE_STUDY" in keys
    assert "ACCEL_DEPREC" in keys

def test_meta_excerpt_matches_expected_patterns():
    text = (FIX / "meta_2024_10k_excerpt.txt").read_text()
    hits = scan_text(text)
    keys = {h["key"] for h in hits}
    assert "META_5_5_YEARS" in keys
    assert "ESTIMATE_CHANGE" in keys

def test_decoy_does_not_match():
    text = (FIX / "decoy_useful_life.txt").read_text()
    assert scan_text(text) == []

def test_severity_rank_orders_highest():
    assert MAX_SEVERITY_RANK(["MED", "HIGH", "MED"]) == "HIGH"
    assert MAX_SEVERITY_RANK(["CRITICAL", "HIGH"]) == "CRITICAL"
    assert MAX_SEVERITY_RANK(["MED"]) == "MED"

def test_snippet_is_truncated():
    text = "x " * 1000 + "from six years to five years " + "y " * 1000
    hits = scan_text(text)
    assert any(len(h["snippet"]) <= 240 for h in hits)
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/test_c1_regex.py -v
```
Expected: ModuleNotFoundError on `catalysts.c1_depreciation`.

- [ ] **Step 3: Write the regex layer in `catalysts/c1_depreciation.py`**

```python
import re

PATTERNS: list[tuple[str, str, str]] = [
    ("USEFUL_LIFE_SHORTENED_6_TO_5",
     r"from\s+(?:six|6)\s+years?\s+to\s+(?:five|5)\s+years?", "HIGH"),
    ("USEFUL_LIFE_EXTENDED_4_TO_6",
     r"from\s+(?:four|4)\s+years?\s+to\s+(?:six|6)\s+years?", "MED"),
    ("USEFUL_LIFE_STUDY",
     r"useful\s+life\s+stud(?:y|ies)", "HIGH"),
    ("AMZN_SUBSET_PHRASE",
     r"subset\s+of\s+(?:our\s+)?servers?\s+and\s+networking\s+equipment", "HIGH"),
    ("ESTIMATE_CHANGE",
     r"change\s+in\s+(?:accounting\s+)?estimate[^.]{0,120}(?:server|network|equipment)", "HIGH"),
    ("META_5_5_YEARS",
     r"(?:5\.5|five\s+and\s+a\s+half)\s+years?", "MED"),
    ("ACCEL_DEPREC",
     r"accelerated\s+depreciation[^.]{0,100}(?:server|gpu|network)", "HIGH"),
    ("IMPAIRMENT_PPE",
     r"impair(?:ment|ed)[^.]{0,80}property\s+and\s+equipment", "HIGH"),
]
_COMPILED = [(k, re.compile(p, re.I | re.S), s) for k, p, s in PATTERNS]

_SEVERITY_ORDER = {"LOG": 0, "MED": 1, "HIGH": 2, "CRITICAL": 3}


def MAX_SEVERITY_RANK(severities: list[str]) -> str:
    return max(severities, key=lambda s: _SEVERITY_ORDER[s])


def scan_text(text: str) -> list[dict]:
    out: list[dict] = []
    for key, rx, sev in _COMPILED:
        m = rx.search(text)
        if m:
            out.append({"key": key, "severity": sev, "snippet": m.group(0)[:240]})
    return out
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/test_c1_regex.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add catalysts/c1_depreciation.py tests/test_c1_regex.py
git commit -m "feat(c1): regex pack + scan_text + canary tests on AMZN/META fixtures"
```

---

## Task 3: `Catalyst1.run()` end-to-end

**Files:**
- Modify: `catalysts/c1_depreciation.py` — add `Catalyst1` class and helpers
- Test: `tests/test_c1_run.py`

Behavior:
- Iterate `config.HYPERSCALERS`.
- For each ticker/CIK, call `edgar.recent_filings(cik, forms=("10-K","10-Q"))`.
- Skip filing if `state.seen("c1_filings", accession)` is True.
- Else fetch text, run `scan_text`, if hits non-empty produce one `Alert`.
- Always `mark_seen` afterwards (even on no hits) so we don't re-scan.
- `Alert` subject: `[C1-{SEV}] {TICKER} {FORM}: depreciation language change detected`.
- `Alert` body: filing URL, accession, filed date, then one line per hit `- {key} ({sev}): {snippet}`.
- Constructor accepts optional `edgar`, `state` for injection.

- [ ] **Step 1: Write `tests/test_c1_run.py`**

```python
from pathlib import Path
from unittest.mock import MagicMock
from catalysts.c1_depreciation import Catalyst1
from lib.edgar import Filing
from lib.state import State

FIX = Path(__file__).parent / "fixtures"

def _filing(cik, acc, form="10-K", primary="x.htm"):
    return Filing(
        cik=cik, accession=acc, form=form, filed_date="2025-02-07",
        primary_document=primary,
        url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-','')}/{primary}",
    )

def test_run_emits_alert_when_filing_matches(tmp_path):
    text = (FIX / "amzn_2024_10k_excerpt.txt").read_text()
    edgar = MagicMock()
    # Only return one filing for AMZN; empty for everyone else.
    def recent(cik, forms, limit=20):
        if cik == "0001018724":
            return [_filing("0001018724", "0001018724-25-000004")]
        return []
    edgar.recent_filings.side_effect = recent
    edgar.get_filing_text.return_value = text

    st = State("c1", db_path=tmp_path / "t.sqlite")
    cat = Catalyst1(edgar=edgar, state=st)
    alerts = cat.run()
    assert len(alerts) == 1
    a = alerts[0]
    assert a.catalyst == "C1"
    assert a.severity == "HIGH"
    assert "AMZN" in a.subject and "10-K" in a.subject
    assert "0001018724-25-000004" in a.body
    assert "AMZN_SUBSET_PHRASE" in a.body or "USEFUL_LIFE_SHORTENED_6_TO_5" in a.body

def test_run_skips_already_seen_filings(tmp_path):
    edgar = MagicMock()
    edgar.recent_filings.side_effect = lambda cik, forms, limit=20: (
        [_filing("0001018724", "0001018724-25-000004")] if cik == "0001018724" else []
    )
    edgar.get_filing_text.return_value = (FIX / "amzn_2024_10k_excerpt.txt").read_text()

    st = State("c1", db_path=tmp_path / "t.sqlite")
    cat = Catalyst1(edgar=edgar, state=st)
    first = cat.run()
    assert len(first) == 1
    second = cat.run()
    assert second == []
    # get_filing_text should NOT have been called the second pass for the skipped filing.
    assert edgar.get_filing_text.call_count == 1

def test_run_emits_no_alert_when_no_match(tmp_path):
    edgar = MagicMock()
    edgar.recent_filings.side_effect = lambda cik, forms, limit=20: (
        [_filing("0001018724", "0001018724-25-000999")] if cik == "0001018724" else []
    )
    edgar.get_filing_text.return_value = (FIX / "decoy_useful_life.txt").read_text()

    st = State("c1", db_path=tmp_path / "t.sqlite")
    cat = Catalyst1(edgar=edgar, state=st)
    assert cat.run() == []
    # But filing accession should be marked seen so we don't re-fetch.
    assert st.seen("c1_filings", "0001018724-25-000999") is True
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/test_c1_run.py -v
```
Expected: AttributeError / ImportError (Catalyst1 not defined yet).

- [ ] **Step 3: Append `Catalyst1` class to `catalysts/c1_depreciation.py`**

Add below the existing `scan_text` definition:

```python
from lib.config import HYPERSCALERS
from lib.edgar import EdgarClient
from lib.state import State
from catalysts.base import Alert, CatalystBase

_FORMS = ("10-K", "10-Q")


def _render_body(ticker: str, filing, hits: list[dict]) -> str:
    lines = [
        f"Ticker:    {ticker}",
        f"Form:      {filing.form}",
        f"Filed:     {filing.filed_date}",
        f"Accession: {filing.accession}",
        f"URL:       {filing.url}",
        "",
        "Pattern hits:",
    ]
    for h in hits:
        snippet = h["snippet"].replace("\n", " ")
        lines.append(f"- {h['key']} ({h['severity']}): {snippet}")
    return "\n".join(lines)


class Catalyst1(CatalystBase):
    name = "GPU Depreciation Useful-Life Changes"

    def __init__(self, edgar: EdgarClient | None = None, state: State | None = None,
                 watchlist: dict[str, str] | None = None):
        self._edgar = edgar or EdgarClient()
        self._state = state or State("c1")
        self._watchlist = watchlist if watchlist is not None else HYPERSCALERS

    def run(self) -> list[Alert]:
        alerts: list[Alert] = []
        for ticker, cik in self._watchlist.items():
            for filing in self._edgar.recent_filings(cik, forms=_FORMS):
                if self._state.seen("c1_filings", filing.accession):
                    continue
                text = self._edgar.get_filing_text(filing)
                hits = scan_text(text)
                self._state.mark_seen("c1_filings", filing.accession)
                if not hits:
                    continue
                sev = MAX_SEVERITY_RANK([h["severity"] for h in hits])
                alerts.append(Alert(
                    catalyst="C1",
                    severity=sev,
                    subject=f"[C1-{sev}] {ticker} {filing.form}: depreciation language change detected",
                    body=_render_body(ticker, filing, hits),
                ))
        return alerts
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/test_c1_run.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Run full suite**

```bash
pytest -v
```
Expected: all tests pass (Foundation's 18 + Catalyst 1's 9 = 27).

- [ ] **Step 6: Commit**

```bash
git add catalysts/c1_depreciation.py tests/test_c1_run.py
git commit -m "feat(c1): Catalyst1.run() — scan watchlist 10-K/10-Q filings and emit alerts"
```

---

## Task 4: CLI entry-point with `--dry-run`

**Files:**
- Modify: `catalysts/c1_depreciation.py` — add `__main__` block + CLI

- [ ] **Step 1: Append CLI to `catalysts/c1_depreciation.py`**

```python
def _main(argv: list[str] | None = None) -> int:
    import argparse, sys
    from lib.notify import send_alert

    p = argparse.ArgumentParser(description="Catalyst 1: GPU Depreciation scanner")
    p.add_argument("--dry-run", action="store_true",
                   help="print alerts instead of emailing")
    args = p.parse_args(argv)

    cat = Catalyst1()
    alerts = cat.run()
    if not alerts:
        print("c1: no alerts")
        return 0
    for a in alerts:
        if args.dry_run:
            print("=" * 72)
            print(a.subject)
            print(a.body)
        else:
            send_alert(a.subject, a.body, severity=a.severity)
    print(f"c1: {len(alerts)} alert(s) {'printed' if args.dry_run else 'emailed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
```

- [ ] **Step 2: Verify CLI parses**

```bash
. .venv/bin/activate
python -m catalysts.c1_depreciation --help
```
Expected: argparse usage printed, exit 0.

- [ ] **Step 3: Commit**

```bash
git add catalysts/c1_depreciation.py
git commit -m "feat(c1): CLI with --dry-run"
```

---

## Task 5: Live dry-run sanity check

This task is interactive — the user verifies a real EDGAR poll works.

- [ ] **Step 1: Live dry-run**

```bash
. .venv/bin/activate
export SEC_USER_AGENT="catalyst-tracker cyprien0312@gmail.com"
python -m catalysts.c1_depreciation --dry-run
```

Expected behavior:
- No crashes, no rate-limit errors.
- Either prints `c1: no alerts` (likely — depends on what's currently in each company's most recent 10-K/10-Q vs the regex set) OR prints one or more alerts with verbatim snippets.
- Subsequent runs print `c1: no alerts` because accessions are now in `state/tracker.sqlite`.

Notes:
- First run will fetch up to 6 × ~20 filings worth of submissions JSON and a subset of HTML documents. Expect 30s–2min.
- If any HTTP 4xx errors fire, check `SEC_USER_AGENT` is set and contains a real email.

- [ ] **Step 2: Inspect state**

```bash
sqlite3 state/tracker.sqlite "SELECT table_name, COUNT(*) FROM seen GROUP BY table_name;"
```
Expected: at least `c1_filings | <N>` where N matches the count of filings scanned.

- [ ] **Step 3: Commit state snapshot**

```bash
git add state/tracker.sqlite
git commit -m "state: initial c1 baseline seed"
```

(Subsequent operational commits will be made by GitHub Actions in a later plan.)

---

## Task 6: Self-review checklist

Before declaring done:

- [ ] All 27 tests pass: `pytest -v`
- [ ] No placeholder strings (`TODO`, `TBD`) anywhere in `catalysts/c1_depreciation.py`
- [ ] AMZN and META fixture files match the verbatim 2024 10-K text from the source spec (§3-C1)
- [ ] Decoy fixture produces zero hits
- [ ] `python -m catalysts.c1_depreciation --dry-run` ran cleanly against live EDGAR
- [ ] `state/tracker.sqlite` committed

Plan complete. Next phases (per source spec build order recommendation, in source-spec.md §recommendations):
- Catalyst 2 (Neoclouds)
- Catalyst 4 (Capex)
- Catalyst 3 (OpenAI)
- Catalyst 5 (Grid)
- GitHub Actions workflows + dashboard

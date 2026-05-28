# C5 PJM Endpoint Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore C5 alert generation. As of 2026-05-29 the PJM queue endpoint hard-coded in `lib/grid_queues.py` returns 404 (PJM restructured their site), and because `c5_grid.run()` calls `pjm_active_queue()` before CAISO and Henry Hub, the entire C5 catalyst raises and produces zero alerts — including the unrelated CAISO and Henry Hub paths.

**Architecture:** Three phases. Phase A is a safety net (decouple PJM failure from the rest of C5) and ships within an hour. Phase B is the actual PJM fix — pick one of two approaches. Phase C is a cosmetic cleanup.

- **Phase A — Triage** (small, mandatory): Make C5's three sources independent. PJM failing must not block CAISO or Henry Hub.
- **Phase B — PJM restoration** (one of B1 OR B2):
  - **B1: Rediscover the new PJM endpoint** by inspecting the modern `pjm.com/planning/services-requests` page network traffic. Lowest schema risk (we already know how to parse PJM XLSX), highest discovery risk (the new endpoint may require login).
  - **B2: Switch to LBNL Queued Up** — Berkeley Lab's aggregated ISO queue snapshot dataset. Stable academic source, includes all ISOs (could subsume CAISO too), but a different schema we'd have to map.
- **Phase C — Cosmetic** (optional): The `run_cli` end-of-run print currently says "N alert(s) emailed" regardless of whether emails were actually sent (e.g. when muted). Change wording to "recorded".

**Tech Stack:** Python 3.11, requests, pandas, openpyxl. For Phase B1 discovery: browser DevTools (manual) or Playwright (automated). For Phase B2: requests + LBNL JSON/XLSX schemas.

**Out of scope:** No changes to C5's transition semantics (MW drops, withdrawals, Henry Hub thresholds). No new catalysts. No GitHub Actions changes.

---

## File Structure

**Files touched:**
- `catalysts/c5_grid.py` — wrap each source in try/except so one failure doesn't sink the others (Phase A).
- `lib/grid_queues.py` — either swap `PJM_QUEUE_URL` and adjust headers (Phase B1) OR rewrite `pjm_active_queue()` to read from LBNL (Phase B2).
- `tests/test_c5.py` — add a regression: a mocked PJM 404 must NOT prevent CAISO + Henry Hub paths from running (Phase A).
- `catalysts/base.py:run_cli` — change the trailing print line wording (Phase C, one-line).
- `CLAUDE.md` — remove the "Known broken" note once the fix lands.

**No new files** for Phase A and B1. Phase B2 may add `lib/lbnl_queues.py` if the LBNL schema work warrants its own module.

---

## Phase A — Decouple PJM failure from the rest of C5

### Task A1: Make C5 sources independent

**Files:**
- Modify: `catalysts/c5_grid.py` — the `run()` method, around the PJM/CAISO/Henry Hub call sites
- Test: `tests/test_c5.py` — add `test_pjm_404_does_not_block_caiso_or_henry_hub`

**Pre-step:** Read the current `catalysts/c5_grid.py` to identify the exact call sites and the structure of `run()`. The plan steps below assume the standard pattern (three sequential calls to `pjm_active_queue()`, `caiso_queue()`, and an EIA Henry Hub fetcher) but you must verify before patching.

- [ ] **Step 1: Write the failing test** — append to `tests/test_c5.py`:

```python
from unittest.mock import patch
from requests.exceptions import HTTPError


def test_pjm_404_does_not_block_caiso_or_henry_hub(monkeypatch, tmp_path):
    """If PJM raises, C5 must still attempt CAISO and Henry Hub paths."""
    import pandas as pd
    # Force PJM to raise like the current production 404
    def boom():
        raise HTTPError("404 PJM")
    monkeypatch.setattr("lib.grid_queues.pjm_active_queue", boom)
    # Stub the other two so we can confirm they were called
    calls = {"caiso": 0, "henry": 0}
    def fake_caiso():
        calls["caiso"] += 1
        return pd.DataFrame({"MW Capacity": [100]})
    monkeypatch.setattr("lib.grid_queues.caiso_queue", fake_caiso)
    # Henry Hub fetcher — adapt selector to wherever it lives in c5_grid
    # (likely lib.eia.henry_hub_strip or similar; verify in the file).
    # For now assert the test framework wires by checking caiso runs:
    from catalysts.c5_grid import C5Grid
    # Use whatever entry point exists; this is illustrative — adjust to real API.
    cat = C5Grid()
    cat.run()  # must not raise
    assert calls["caiso"] >= 1, "CAISO path must run even after PJM failure"
```

**Note to implementer:** the test above is illustrative — the exact mocking points depend on the real `C5Grid` shape. Read the file, find the actual source-call sites, and rewrite the mocks to match. The core assertion stays: **PJM raising must not prevent the other two sources from being attempted**.

- [ ] **Step 2: Run the test, confirm it fails:**

```bash
.venv/bin/pytest tests/test_c5.py::test_pjm_404_does_not_block_caiso_or_henry_hub -v
```
Expected: FAIL (PJM exception propagates through `run()`).

- [ ] **Step 3: Wrap each source in its own try/except** inside `c5_grid.py:run()`. Pattern:

```python
from lib.log import get_logger
log = get_logger(__name__)

# Inside run():
alerts: list[Alert] = []

try:
    pjm_df = pjm_active_queue()
    alerts.extend(self._process_pjm(pjm_df))
except Exception as e:
    log.warning("c5.pjm source failed: %s", e)

try:
    caiso_df = caiso_queue()
    alerts.extend(self._process_caiso(caiso_df))
except Exception as e:
    log.warning("c5.caiso source failed: %s", e)

try:
    alerts.extend(self._process_henry_hub())
except Exception as e:
    log.warning("c5.henry_hub source failed: %s", e)

return alerts
```

Adapt method names to whatever the file actually uses. The constraint: **each source is independently guarded**, exceptions are logged at WARNING (not silently swallowed), and an empty list is the worst-case return.

- [ ] **Step 4: Run the new test + full suite:**

```bash
.venv/bin/pytest tests/test_c5.py -v
.venv/bin/pytest -v 2>&1 | tail -5
```
Expected: new test passes; existing C5 tests still pass.

- [ ] **Step 5: Smoke-test against production state on the host:**

```bash
set -a; source ~/.catalyst.env; set +a
.venv/bin/python -m catalysts.c5_grid 2>&1 | tail -10
```
Expected: prints `c5.pjm source failed: 404...` at WARNING, then either `c5: no alerts` (CAISO/Henry Hub didn't trigger) or `c5: N alert(s) emailed`. **No exception** to stdout.

- [ ] **Step 6: Commit:**

```bash
git add catalysts/c5_grid.py tests/test_c5.py
git commit -m "c5: isolate PJM failure so CAISO + Henry Hub still run"
```

---

## Phase B — Restore PJM data

Choose ONE of B1 or B2. Default: start with B1 because the schema work is zero (we already parse PJM XLSX correctly). Escalate to B2 if B1 hits a login wall.

### Task B1: Rediscover the new PJM endpoint

**Files:**
- Modify: `lib/grid_queues.py:PJM_QUEUE_URL` (and possibly `HEADERS`)
- No new test code needed — Phase A's test continues to mock at the function level.

**Pre-work — manual discovery** (the implementer should do this, not assume):

1. Open `https://www.pjm.com/planning/services-requests` in a desktop browser with DevTools → Network tab.
2. Click any "Download", "Export", "Excel", or queue-status link.
3. Filter the Network tab by `xhr`, `xlsx`, or `services`. Note the full request URL, method, and any headers (especially `Authorization`, `Cookie`, `X-Csrf-Token`).
4. If the request requires auth → escalate to B2. Otherwise capture: URL, method, query params, and any custom headers required.

- [ ] **Step 1: Verify the candidate URL with curl** (before editing):

```bash
# Replace with the URL captured in DevTools
NEW_URL="https://NEW.PJM.URL/path/to/export.xlsx"
curl -sIL -A "catalyst-tracker test" -o /dev/null -w "%{http_code} %{content_type} %{size_download}\n" "$NEW_URL"
```
Expected: `200 application/vnd.openxmlformats-officedocument.spreadsheetml.sheet <large>`. If 4xx or HTML, the URL is wrong or needs auth — stop and report.

- [ ] **Step 2: Download once and inspect schema** so we know whether existing `_coalesce_mw` / `summarize` still work:

```bash
curl -sL -A "catalyst-tracker test" -o /tmp/pjm_new.xlsx "$NEW_URL"
.venv/bin/python -c "
import pandas as pd
df = pd.read_excel('/tmp/pjm_new.xlsx')
print('rows:', len(df))
print('cols:', list(df.columns)[:20])
"
```
Expected: column names should include something parseable as MW (matches one of the candidates in `lib.grid_queues._coalesce_mw`: `MW Capacity`, `MW Energy`, `MW`, `Total Capacity`, `Capacity (MW)`, `Project MW`, `Generating Facility Capacity`) and a status-like column. If neither is present, the schema changed — either extend `_coalesce_mw`'s candidate list OR escalate to B2.

- [ ] **Step 3: Update `lib/grid_queues.py:PJM_QUEUE_URL`** to the new URL. If the new endpoint needs a custom header (e.g. `Accept: application/octet-stream`), extend `HEADERS` or pass per-call headers in `_read_xlsx`.

- [ ] **Step 4: Run C5 end-to-end on the host:**

```bash
set -a; source ~/.catalyst.env; set +a
.venv/bin/python -m catalysts.c5_grid 2>&1 | tail -10
```
Expected: no PJM warning in log. If transition baseline isn't in `c5_queues` yet (first run after URL change), the baseline gets re-established and you'll see `c5: no alerts` from PJM specifically — that's correct, alerts will appear on the next snapshot.

- [ ] **Step 5: Run tests:**

```bash
.venv/bin/pytest tests/test_c5.py -v
.venv/bin/pytest -v 2>&1 | tail -3
```

- [ ] **Step 6: Remove the "Known broken" note from `CLAUDE.md`** — find the `lib/grid_queues.py` bullet and revert it to the original short description.

- [ ] **Step 7: Commit:**

```bash
git add lib/grid_queues.py CLAUDE.md
git commit -m "c5: update PJM queue URL after their 2026 site restructure"
```

### Task B2 (alternative to B1): Switch to LBNL Queued Up

Only run this if B1 hit a login wall or the PJM schema changed beyond what `_coalesce_mw` can absorb.

**Files:**
- Create: `lib/lbnl_queues.py`
- Modify: `lib/grid_queues.py:pjm_active_queue` — proxy to `lib.lbnl_queues.pjm_from_lbnl()`
- Test: `tests/test_lbnl_queues.py` — schema mapping test against a checked-in fixture

**Pre-work:** confirm LBNL's current download URL and schema by browsing https://emp.lbl.gov/queues, downloading the latest queue snapshot, and noting:
- the URL pattern
- a column-name mapping table (MW, status, ISO, project name)
- update cadence (LBNL refreshes infrequently — typically annual; this may make C5's transition signals slower but still useful)

- [ ] **Step 1: Build a fixture from a one-time download:**

```bash
curl -sL "<lbnl URL>" -o tests/fixtures/lbnl_queues_sample.xlsx
.venv/bin/python -c "
import pandas as pd
df = pd.read_excel('tests/fixtures/lbnl_queues_sample.xlsx')
print(df.columns.tolist()[:30])
print(df.head(3))
"
```

- [ ] **Step 2: Write failing test** — `tests/test_lbnl_queues.py`:

```python
from pathlib import Path
import pandas as pd
from lib.lbnl_queues import pjm_from_lbnl


def test_pjm_from_lbnl_returns_pjm_only_with_expected_columns(monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "lbnl_queues_sample.xlsx"
    monkeypatch.setattr("lib.lbnl_queues._download", lambda: pd.read_excel(fixture))
    df = pjm_from_lbnl()
    assert len(df) > 0
    assert (df["iso"] == "PJM").all()
    assert "mw" in df.columns
    assert "status" in df.columns
```

- [ ] **Step 3: Run the test, confirm it fails** (module doesn't exist yet).

- [ ] **Step 4: Implement `lib/lbnl_queues.py`** with `_download()` (URL fetch), `pjm_from_lbnl()` filtering ISO==PJM, and column renames so downstream `summarize()` in `lib/grid_queues.py` still works. Keep the function signature compatible with the existing `pjm_active_queue` so `c5_grid.py` doesn't need to know which source it's reading from.

- [ ] **Step 5: In `lib/grid_queues.py`**, make `pjm_active_queue()` thin:

```python
def pjm_active_queue() -> pd.DataFrame:
    from lib.lbnl_queues import pjm_from_lbnl
    return pjm_from_lbnl()
```

- [ ] **Step 6: Run tests + host smoke:**

```bash
.venv/bin/pytest tests/test_lbnl_queues.py tests/test_c5.py -v
.venv/bin/python -m catalysts.c5_grid 2>&1 | tail -10
```

- [ ] **Step 7: Update `CLAUDE.md`** `lib/grid_queues.py` bullet — note the data source is now LBNL Queued Up for the PJM column (CAISO still direct). Remove "Known broken".

- [ ] **Step 8: Commit:**

```bash
git add lib/lbnl_queues.py lib/grid_queues.py tests/test_lbnl_queues.py tests/fixtures/lbnl_queues_sample.xlsx CLAUDE.md
git commit -m "c5: switch PJM queue source to LBNL Queued Up after PJM endpoint removal"
```

---

## Phase C — Cosmetic: "emailed" count print is misleading when muted

Currently `catalysts/base.py:run_cli` prints `"{tag}: {len(alerts)} alert(s) emailed"` even when the catalyst is in `CATALYST_EMAIL_DISABLE` and no email was sent. Cron logs are the only place this surfaces — but it's actively misleading when debugging mute behaviour.

**Files:**
- Modify: `catalysts/base.py:82`

- [ ] **Step 1: Change the print to `"recorded"` when not dry-run:**

```python
    print(f"{tag}: {len(alerts)} alert(s) {'printed' if args.dry_run else 'recorded'}")
```

(One-character semantic change. "recorded" is true regardless of mute state — every fresh alert is recorded in the `alerts` table whether or not it emailed.)

- [ ] **Step 2: Run full suite:**

```bash
.venv/bin/pytest -v 2>&1 | tail -3
```
Expected: still green (no test asserts the exact print wording).

- [ ] **Step 3: Commit:**

```bash
git add catalysts/base.py
git commit -m "base: print 'recorded' instead of 'emailed' since alerts may be muted"
```

---

## Self-Review

**Spec coverage:**
- ✅ C5 currently fails entirely → Phase A guarantees CAISO + Henry Hub run independently.
- ✅ PJM data source restored → Phase B1 (preferred) or B2 (fallback).
- ✅ Misleading log line → Phase C.
- ✅ Documentation updated (CLAUDE.md "Known broken" note removed once B1 or B2 lands).

**Placeholder scan:**
- Phase A Step 1 test contains a deliberate marker that the implementer "must adapt to the real C5Grid shape" — this is intentional, not a placeholder. The implementer is told to read the file before pattern-matching.
- Phase B1 has placeholders (`NEW_URL`) by design — the URL must be captured manually from DevTools; we don't know it yet. The Bash steps treat it as a shell variable so the implementer can substitute and run.
- Phase B2 likewise has `<lbnl URL>` because LBNL's download URL is not stable enough to hardcode in a plan written in advance of discovery.

**Type consistency:** `pjm_active_queue()` keeps its `() -> pd.DataFrame` signature whether B1 or B2 is chosen. Downstream `summarize()` is unchanged.

**Trade-offs:**
- Phase A's broad `except Exception` is intentional — at the runtime boundary we want resilience, not type-narrow handling. Each failure logs at WARNING, not ERROR, because cron will retry every 30 min and a transient hiccup isn't worth paging anyone.
- If B2 is chosen, C5's PJM signal lags by however long LBNL takes to refresh. The MW-drop / withdrawals transitions still fire; they're just less timely. Acceptable for a "macro stress" signal.
- Phase C is low-value and may be skipped if reviewers prefer fewer commits — but it's a 1-line change that removes real log confusion.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-29-c5-pjm-endpoint-fix.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task with two-stage review.
2. **Inline Execution** — execute tasks in this session with checkpoints.

For B1 vs B2: do Phase A first (it stands alone and stabilizes C5 immediately). Pause after A to decide B1 or B2 based on what manual DevTools inspection of PJM's new site reveals. Phase C any time.

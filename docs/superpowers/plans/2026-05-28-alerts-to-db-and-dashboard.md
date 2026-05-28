# Alerts-to-DB + Per-Catalyst Email Mute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every alert to a new `alerts` table in `state/tracker.sqlite` and render them in the GitHub Pages dashboard, so the user can mute noisy catalysts (starting with C3) at the email layer without losing visibility.

**Architecture:** Add a `catalyst` argument to `lib.notify.send_alert`. Persist every fresh (non-deduped) alert into a new `alerts` table. Skip the SMTP send when the catalyst tag appears in the `CATALYST_EMAIL_DISABLE` env var. Extend `scripts/build_dashboard.py` to query the new table and render a "Recent alerts" section in `docs/index.html` with severity/catalyst filters and browser-local read-state tracking via `localStorage`.

**Tech Stack:** Python 3.11, SQLite (existing `state/tracker.sqlite`), Jinja2 (existing inline template in `build_dashboard.py`), vanilla JS for client-side read-state (no new deps).

**Out of scope:** No server-side read-state (would require a backend; GitHub Pages is static). No retroactive backfill of past alerts (they were emitted before the table existed). No changes to other catalysts' alert content.

---

## File Structure

**Files to modify:**
- `lib/state.py` — add `alerts` table to `_SCHEMA`
- `lib/notify.py` — add `catalyst` param, env-driven mute, DB persistence
- `catalysts/base.py` — pass tag to `send_alert`
- `scripts/build_dashboard.py` — query `alerts` table, extend template with filters + localStorage read tracking
- `tests/test_notify.py` — extend existing tests
- `CLAUDE.md` and `README.md` — document `CATALYST_EMAIL_DISABLE`
- `~/.catalyst.env` (NOT in repo) — user adds `CATALYST_EMAIL_DISABLE=c3` manually after deployment

**No new files** — fits cleanly into existing module boundaries.

---

### Task 1: Add `alerts` table to SQLite schema

**Files:**
- Modify: `lib/state.py:8-15` (`_SCHEMA` constant)
- Test: `tests/test_state.py` (extend)

- [ ] **Step 1: Write failing test** — append to `tests/test_state.py`:

```python
def test_alerts_table_created():
    import tempfile, sqlite3
    from pathlib import Path
    from lib.state import State
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.sqlite"
        State("x", db_path=db)
        with sqlite3.connect(db) as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(alerts)")}
        assert {"id", "ts", "catalyst", "severity", "subject", "body", "emailed", "fingerprint"} <= cols
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/test_state.py::test_alerts_table_created -v
```
Expected: FAIL — `alerts` table doesn't exist.

- [ ] **Step 3: Extend `_SCHEMA` in `lib/state.py`** — append to the existing schema string:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    table_name TEXT NOT NULL,
    key        TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    PRIMARY KEY(table_name, key)
);
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    catalyst    TEXT NOT NULL,
    severity    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    emailed     INTEGER NOT NULL DEFAULT 0,
    fingerprint TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts DESC);
"""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_state.py::test_alerts_table_created -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/state.py tests/test_state.py
git commit -m "state: add alerts table for dashboard-visible alert history"
```

---

### Task 2: Update `send_alert` to persist and gate on `CATALYST_EMAIL_DISABLE`

**Files:**
- Modify: `lib/notify.py` (whole file)
- Test: `tests/test_notify.py` (extend)

- [ ] **Step 1: Write failing tests** — append to `tests/test_notify.py`:

```python
import sqlite3

@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_persists_row(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp_cls.return_value.__enter__.return_value = MagicMock()
    send_alert("subj", "body", severity="HIGH", catalyst="c3", state=st)
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        rows = c.execute("SELECT catalyst, severity, subject, emailed FROM alerts").fetchall()
    assert rows == [("c3", "HIGH", "subj", 1)]


@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_skips_email_when_catalyst_disabled(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CATALYST_EMAIL_DISABLE", "c3")
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp = smtp_cls.return_value.__enter__.return_value = MagicMock()
    sent = send_alert("subj", "body", severity="HIGH", catalyst="c3", state=st)
    assert sent is False
    smtp.send_message.assert_not_called()
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        rows = c.execute("SELECT catalyst, emailed FROM alerts").fetchall()
    assert rows == [("c3", 0)]


@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_disable_list_is_csv(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CATALYST_EMAIL_DISABLE", "c2, c3 ,c5")
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp = smtp_cls.return_value.__enter__.return_value = MagicMock()
    send_alert("a", "body", catalyst="c3", state=st)
    send_alert("b", "body", catalyst="c1", state=st)
    assert smtp.send_message.call_count == 1


@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_dedup_prevents_second_db_row(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp_cls.return_value.__enter__.return_value = MagicMock()
    send_alert("subj", "body", catalyst="c1", state=st)
    send_alert("subj", "body", catalyst="c1", state=st)
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        n = c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert n == 1
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_notify.py -v
```
Expected: 4 new tests FAIL (TypeError on `catalyst=` kwarg / no `alerts` rows written).

- [ ] **Step 3: Rewrite `lib/notify.py`**:

```python
import hashlib
import os
import smtplib
import time
from email.message import EmailMessage

from lib.config import require_env
from lib.state import State

DEDUP_TTL_SECONDS = 7 * 86400


def _fingerprint(subject: str, body: str) -> str:
    return hashlib.sha256(f"{subject}|{body[:500]}".encode()).hexdigest()


def _email_disabled_for(catalyst: str | None) -> bool:
    if not catalyst:
        return False
    raw = os.environ.get("CATALYST_EMAIL_DISABLE", "")
    disabled = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return catalyst.lower() in disabled


def _persist_alert(st: State, *, ts: int, catalyst: str, severity: str,
                   subject: str, body: str, emailed: bool, fingerprint: str) -> None:
    with st.connection() as c:
        c.execute(
            "INSERT INTO alerts(ts, catalyst, severity, subject, body, emailed, fingerprint) "
            "VALUES (?,?,?,?,?,?,?)",
            (ts, catalyst, severity, subject, body, 1 if emailed else 0, fingerprint),
        )


def send_alert(subject: str, body: str, severity: str = "MED",
               catalyst: str | None = None,
               state: State | None = None) -> bool:
    """Send an alert. Returns True iff an email was sent.

    Always persists a row to `alerts` table on first sighting (regardless of
    whether the email was sent), respecting the 7-day dedup window on
    (subject, body[:500]).
    """
    st = state or State("notify")
    fp = _fingerprint(subject, body)
    if st.seen("alerts_dedup", fp, ttl_seconds=DEDUP_TTL_SECONDS):
        return False

    tag = (catalyst or "").lower() or "unknown"
    email_muted = _email_disabled_for(catalyst)
    emailed = False

    if not email_muted:
        gmail_user = require_env("GMAIL_USER")
        gmail_pw = require_env("GMAIL_APP_PASSWORD")
        alert_to = require_env("ALERT_TO")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = alert_to
        msg["X-Catalyst-Severity"] = severity
        msg.set_content(body)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(gmail_user, gmail_pw)
            s.send_message(msg)
        emailed = True

    _persist_alert(
        st,
        ts=int(time.time()),
        catalyst=tag,
        severity=severity,
        subject=subject,
        body=body,
        emailed=emailed,
        fingerprint=fp,
    )
    st.mark_seen("alerts_dedup", fp)
    return emailed
```

- [ ] **Step 4: Run all notify tests**

```bash
.venv/bin/pytest tests/test_notify.py -v
```
Expected: all PASS (4 new + 4 existing).

- [ ] **Step 5: Commit**

```bash
git add lib/notify.py tests/test_notify.py
git commit -m "notify: persist alerts to DB, add CATALYST_EMAIL_DISABLE env var"
```

---

### Task 3: Pass catalyst tag from CLI runner

**Files:**
- Modify: `catalysts/base.py:75-82`
- Test: extend `tests/test_base.py`

- [ ] **Step 1: Inspect `tests/test_base.py`** to confirm test style:

```bash
.venv/bin/pytest tests/test_base.py -v
cat tests/test_base.py
```

- [ ] **Step 2: Write failing test** — append to `tests/test_base.py`:

```python
from unittest.mock import patch, MagicMock
from catalysts.base import Alert, CatalystBase, run_cli

def test_run_cli_passes_catalyst_tag_to_send_alert():
    class Fake(CatalystBase):
        def run(self):
            return [Alert(catalyst="c3", severity="HIGH", subject="s", body="b")]

    with patch("lib.notify.send_alert") as m:
        run_cli(lambda args: Fake(), description="Catalyst 3: openai", argv=[])
        assert m.called
        kwargs = m.call_args.kwargs
        assert kwargs.get("catalyst") == "c3" or m.call_args.args[-1] == "c3"
```

- [ ] **Step 3: Run to verify it fails**

```bash
.venv/bin/pytest tests/test_base.py -v
```
Expected: FAIL — `catalyst` not currently in kwargs.

- [ ] **Step 4: Update `catalysts/base.py:75-82`** — replace the `else: send_alert(...)` line:

```python
    for a in alerts:
        if args.dry_run:
            print("=" * 72)
            print(a.subject)
            print(a.body)
        else:
            send_alert(a.subject, a.body, severity=a.severity, catalyst=tag)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_base.py tests/test_notify.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add catalysts/base.py tests/test_base.py
git commit -m "base: forward catalyst tag to send_alert for per-cat mute"
```

---

### Task 4: Query `alerts` table in dashboard builder

**Files:**
- Modify: `scripts/build_dashboard.py:31-79` (`collect_status`)

- [ ] **Step 1: Extend `collect_status()` in `scripts/build_dashboard.py`** — inside the function, after the existing `c5_rows` block and before the `return`, add:

```python
    alerts_rows = []
    try:
        with st.connection() as c:
            alerts_rows = c.execute(
                "SELECT id, ts, catalyst, severity, subject, body, emailed "
                "FROM alerts ORDER BY ts DESC LIMIT 200"
            ).fetchall()
    except Exception:
        pass
```

then in the returned dict, add a new key:

```python
        "alerts": [
            {
                "id": r[0],
                "ts": int(r[1]),
                "ts_str": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(r[1]))),
                "catalyst": (r[2] or "").upper(),
                "severity": r[3],
                "subject": r[4],
                "body": r[5],
                "emailed": bool(r[6]),
            }
            for r in alerts_rows
        ],
```

- [ ] **Step 2: Verify the JSON output**

```bash
.venv/bin/python scripts/build_dashboard.py
.venv/bin/python -c "import json; d=json.load(open('docs/data/status.json')); print('alerts key:', 'alerts' in d, 'len:', len(d.get('alerts', [])))"
```
Expected: `alerts key: True len: 0` (no alerts yet — table is empty until next catalyst run).

- [ ] **Step 3: Commit**

```bash
git add scripts/build_dashboard.py
git commit -m "dashboard: include recent alerts in status.json"
```

---

### Task 5: Render alerts in dashboard HTML + filters + localStorage read state

**Files:**
- Modify: `scripts/build_dashboard.py:90-156` (`DEFAULT_TEMPLATE`)

- [ ] **Step 1: Update `DEFAULT_TEMPLATE`** — insert a new `<h2>Recent alerts</h2>` block after the existing `<h2>Catalysts</h2>` table (before `<h2>State table counts</h2>`). The full template body becomes:

```html
<h1>catalyst-tracker</h1>
<div class="meta">Generated {{ s.generated_at_str }} · <a href="thresholds.html">view thresholds →</a></div>

<h2>Catalysts</h2>
<table>
<tr><th>ID</th><th>Name</th></tr>
{% for cat in s.catalysts %}
<tr><td><code>{{ cat.id }}</code></td><td>{{ cat.name }}</td></tr>
{% endfor %}
</table>

<h2>Recent alerts <span id="alerts-count" class="meta"></span></h2>
<div class="alert-toolbar">
  <label>Catalyst:
    <select id="filter-catalyst">
      <option value="">all</option>
      <option value="C1">C1</option><option value="C2">C2</option>
      <option value="C3">C3</option><option value="C4">C4</option>
      <option value="C5">C5</option>
    </select>
  </label>
  <label>Severity:
    <select id="filter-severity">
      <option value="">all</option>
      <option value="CRITICAL">CRITICAL</option>
      <option value="HIGH">HIGH</option>
      <option value="MED">MED</option>
      <option value="LOG">LOG</option>
    </select>
  </label>
  <label><input type="checkbox" id="filter-unread"> only unread</label>
  <button id="mark-all-read" type="button">mark all visible read</button>
  <button id="clear-read" type="button">reset read state</button>
</div>
<div id="alerts-list">
{% for a in s.alerts %}
<details class="alert sev-{{ a.severity }}" data-id="{{ a.id }}" data-catalyst="{{ a.catalyst }}" data-severity="{{ a.severity }}">
  <summary>
    <span class="sev sev-bg-{{ a.severity }}">{{ a.severity }}</span>
    <code>{{ a.catalyst }}</code>
    <span class="subj">{{ a.subject }}</span>
    <span class="meta">{{ a.ts_str }}{% if not a.emailed %} · muted{% endif %}</span>
  </summary>
  <pre>{{ a.body }}</pre>
  <button class="mark-read" type="button" data-id="{{ a.id }}">mark read</button>
</details>
{% else %}
<p class="meta">No alerts recorded yet.</p>
{% endfor %}
</div>

<h2>State table counts</h2>
```

- [ ] **Step 2: Update `<style>` block** — add to the existing `<style>`:

```css
.alert-toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 0.5rem 0 1rem; font-size: 0.9em; }
.alert-toolbar select, .alert-toolbar button { font-size: 0.9em; padding: 2px 6px; }
.alert { border-bottom: 1px solid #eee; padding: 6px 0; }
.alert summary { cursor: pointer; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.alert summary .subj { flex: 1; min-width: 200px; }
.alert pre { background: #f6f6f6; padding: 8px; border-radius: 4px; white-space: pre-wrap; word-break: break-word; }
.alert.read summary { color: #999; }
.alert.read summary .subj { font-weight: normal; }
.sev { display: inline-block; padding: 1px 8px; border-radius: 10px; color: white; font-size: 0.72em; font-weight: 600; letter-spacing: 0.5px; }
.sev-bg-CRITICAL { background: #c0392b; }
.sev-bg-HIGH     { background: #e67e22; }
.sev-bg-MED      { background: #f1c40f; color: #333; }
.sev-bg-LOG      { background: #7f8c8d; }
```

- [ ] **Step 3: Add `<script>` block before `</body>`** in the same template:

```html
<script>
(function () {
  const KEY = "catalyst-tracker:read-ids";
  const read = new Set(JSON.parse(localStorage.getItem(KEY) || "[]"));
  const list = document.getElementById("alerts-list");
  const fCat = document.getElementById("filter-catalyst");
  const fSev = document.getElementById("filter-severity");
  const fUnread = document.getElementById("filter-unread");
  const count = document.getElementById("alerts-count");

  function persist() { localStorage.setItem(KEY, JSON.stringify([...read])); }

  function applyState() {
    let visible = 0;
    for (const el of list.querySelectorAll(".alert")) {
      const id = el.dataset.id;
      const isRead = read.has(id);
      el.classList.toggle("read", isRead);
      const catOK = !fCat.value || el.dataset.catalyst === fCat.value;
      const sevOK = !fSev.value || el.dataset.severity === fSev.value;
      const unreadOK = !fUnread.checked || !isRead;
      const show = catOK && sevOK && unreadOK;
      el.style.display = show ? "" : "none";
      if (show) visible++;
    }
    count.textContent = "(" + visible + " visible)";
  }

  list.addEventListener("click", (e) => {
    const btn = e.target.closest(".mark-read");
    if (!btn) return;
    e.preventDefault();
    read.add(btn.dataset.id);
    persist();
    applyState();
  });

  document.getElementById("mark-all-read").addEventListener("click", () => {
    for (const el of list.querySelectorAll(".alert")) {
      if (el.style.display !== "none") read.add(el.dataset.id);
    }
    persist();
    applyState();
  });

  document.getElementById("clear-read").addEventListener("click", () => {
    if (!confirm("Reset read state on this device?")) return;
    read.clear();
    persist();
    applyState();
  });

  fCat.addEventListener("change", applyState);
  fSev.addEventListener("change", applyState);
  fUnread.addEventListener("change", applyState);
  applyState();
})();
</script>
```

- [ ] **Step 4: Rebuild and eyeball**

```bash
.venv/bin/python scripts/build_dashboard.py
xdg-open docs/index.html 2>/dev/null || echo "open docs/index.html in browser to verify"
```
Expected: page renders, "Recent alerts" section shows "No alerts recorded yet." (because table is still empty before first catalyst run after deployment). Filters present; clicking them doesn't crash.

- [ ] **Step 5: Seed one fake alert and re-verify**

```bash
.venv/bin/python -c "
from lib.state import State
import time
st = State('seed')
with st.connection() as c:
    c.execute('INSERT INTO alerts(ts, catalyst, severity, subject, body, emailed, fingerprint) VALUES (?,?,?,?,?,?,?)',
              (int(time.time()), 'c3', 'CRITICAL', 'TEST OpenAI bond filing', 'Sample body...', 0, 'test-fp'))
"
.venv/bin/python scripts/build_dashboard.py
```
Open `docs/index.html` and verify: row shows, expandable, "mark read" greys it, severity filter hides it when set to HIGH, etc. Then clean the seed:

```bash
.venv/bin/python -c "
from lib.state import State
st = State('seed')
with st.connection() as c:
    c.execute(\"DELETE FROM alerts WHERE fingerprint='test-fp'\")
"
.venv/bin/python scripts/build_dashboard.py
```

- [ ] **Step 6: Commit**

```bash
git add scripts/build_dashboard.py
git commit -m "dashboard: render alerts table with severity/catalyst filters and localStorage read state"
```

---

### Task 6: Document `CATALYST_EMAIL_DISABLE` and dashboard alerts view

**Files:**
- Modify: `CLAUDE.md` (add to Architecture section)
- Modify: `README.md` (add to "Tuning email volume" subsection)

- [ ] **Step 1: Update `CLAUDE.md`** — under the `lib/notify.py` bullet, change to:

```markdown
- `lib/notify.py` — Gmail SMTP send + alert dedup + persistence. **SHA-256 over `(subject, body[:500])` with 7-day TTL** prevents repeat emails AND prevents duplicate `alerts` rows. Every non-deduped alert is INSERTed into the `alerts` table regardless of whether SMTP fired. Set `CATALYST_EMAIL_DISABLE=c3,c5` to silence specific catalysts' emails while keeping their rows in DB. Header `X-Catalyst-Severity:` still set.
```

And in the Commands section, add under "Inspect state":

```bash
sqlite3 state/tracker.sqlite "SELECT ts, catalyst, severity, subject FROM alerts ORDER BY ts DESC LIMIT 20"
```

- [ ] **Step 2: Update `README.md`** — replace the "Tuning email volume" bullet list with:

```markdown
### Tuning email volume

- **Mute a whole catalyst's emails**: add `CATALYST_EMAIL_DISABLE=c3` (CSV) to
  `~/.catalyst.env`. The alert still lands in the `alerts` table and shows up
  in the dashboard, but no email is sent. Useful when one catalyst is too
  chatty (C3 in particular hits frequently because RSS feeds update fast).
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
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document CATALYST_EMAIL_DISABLE and dashboard alerts view"
```

---

### Task 7: Deploy — wire mute in `~/.catalyst.env`

**Files:**
- Modify: `~/.catalyst.env` (NOT in repo, host-only, chmod 600)

- [ ] **Step 1: Append the mute line**

```bash
echo "CATALYST_EMAIL_DISABLE=c3" >> ~/.catalyst.env
```

- [ ] **Step 2: Smoke-test against C3** (`--dry-run` does not exercise `send_alert`, so do a non-dry run if there's a fresh C3 signal; otherwise wait for cron):

```bash
set -a; source ~/.catalyst.env; set +a
.venv/bin/python -m catalysts.c3_openai
# In a separate shell, after it finishes:
sqlite3 state/tracker.sqlite "SELECT ts, catalyst, severity, emailed, subject FROM alerts ORDER BY ts DESC LIMIT 10"
```
Expected: any new C3 rows have `emailed=0`. Inbox does not receive a new email.

- [ ] **Step 3: Verify dashboard picks them up after the next cron run**

```bash
.venv/bin/python scripts/build_dashboard.py
git log --oneline -5
```
Expected: rebuild succeeds, the next cron cycle's auto-commit will push the populated dashboard. Visit GitHub Pages URL to confirm.

---

## Self-Review

**Spec coverage:**
- ✅ Stop C3 emails — Task 2 (`CATALYST_EMAIL_DISABLE`), Task 7 (apply on host).
- ✅ Local DB persistence — Tasks 1, 2 (`alerts` table + INSERT path).
- ✅ Dashboard viewer — Tasks 4, 5 (query + render + filters).
- ✅ Read/unread tracking — Task 5 (localStorage).
- ✅ Only C3 muted, others unchanged — env-var-based; Task 7 only adds `c3`.

**Placeholder scan:** no TBDs, all code blocks complete, all file paths exact.

**Type consistency:**
- `catalyst` param is `str | None` everywhere it appears in `notify.py`.
- DB column names (`catalyst`, `severity`, `subject`, `body`, `emailed`, `fingerprint`, `ts`, `id`) consistent across Task 1 schema, Task 2 INSERT, Task 4 SELECT, Task 5 template.
- `tag` variable in `catalysts/base.py:run_cli` already exists (line 69), reused in Task 3 without renaming.

**Trade-offs the user should know:**
- Read-state in localStorage means it's per-device. If you check on the phone you've "read" something, the laptop won't know. Acceptable for "occasional glance" use case; if it becomes annoying we'd need to move to a server-side `read_at` column and a small local writer (out of scope here).
- `LIMIT 200` in dashboard query is a soft cap. If alert volume grows large, page weight grows linearly — fine until tens of MB.
- Existing dedup unchanged: a muted catalyst still won't double-record the same alert within 7 days.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-alerts-to-db-and-dashboard.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task with two-stage review.
2. **Inline Execution** — execute tasks in this session with checkpoints.

Which approach?

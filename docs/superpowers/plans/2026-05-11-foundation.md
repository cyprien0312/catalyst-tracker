# Catalyst Tracker — Foundation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the catalyst-tracker repo skeleton with shared `lib/` modules (SQLite state, SEC EDGAR client, Gmail alerts, config), a `CatalystBase` ABC, a passing test suite, and a `scripts/test_alert.py` that sends a real email — i.e., the substrate every per-catalyst plan will build on.

**Architecture:** Pure-Python (>=3.11). Each library module is small and has one job. State persisted in `state/tracker.sqlite` via a thin wrapper. Alerts dispatched via Gmail SMTP with SHA-256 dedup. SEC client enforces rate limits + `User-Agent`. `CatalystBase` standardizes `Alert` dataclass + `run() -> list[Alert]`. Tests use `pytest`; HTTP mocked with `responses`.

**Tech Stack:** Python 3.11+, pytest, requests, tenacity, responses (testing). No external services touched in tests; only `test_alert.py` and the manual sanity run hit real Gmail/EDGAR.

**Source spec:** `docs/source-spec.md` (§2, §5, §6, §8, §11).

---

## File Structure

Create:
- `requirements.txt` — runtime deps
- `requirements-dev.txt` — test deps
- `.gitignore`
- `pyproject.toml` (minimal — pytest config + package discovery)
- `lib/__init__.py`
- `lib/config.py` — watchlists, CIKs, env loader
- `lib/state.py` — SQLite wrapper
- `lib/notify.py` — Gmail SMTP + dedup
- `lib/edgar.py` — SEC client (rate-limited, UA-enforced)
- `lib/rate_limit.py` — token-bucket helper
- `catalysts/__init__.py`
- `catalysts/base.py` — `Alert` dataclass + `CatalystBase` ABC
- `scripts/test_alert.py` — manual smoke test for SMTP
- `state/.gitkeep`
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/test_state.py`
- `tests/test_notify.py`
- `tests/test_edgar.py`
- `tests/test_config.py`
- `tests/test_base.py`
- `tests/fixtures/.gitkeep`
- `README.md`

No GitHub Actions workflows yet — those come in the per-catalyst plans, since cron cadence is catalyst-specific. The skeleton is verified locally first.

---

## Task 1: Repo bootstrap

**Files:**
- Create: `.gitignore`, `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `README.md`

- [ ] **Step 1: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.env
.pytest_cache/
*.egg-info/
.DS_Store
state/*.sqlite-journal
state/*.sqlite-wal
state/*.sqlite-shm
```

- [ ] **Step 2: Write `requirements.txt`**

```
requests>=2.32
tenacity>=8.4
python-dateutil>=2.9
```

(Catalyst-specific deps — `feedparser`, `yfinance`, `openpyxl`, `pandas`, `beautifulsoup4`, `lxml`, `jinja2` — will be added by later plans. Foundation stays minimal.)

- [ ] **Step 3: Write `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0
responses>=0.25
```

- [ ] **Step 4: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "catalyst-tracker"
version = "0.0.1"
requires-python = ">=3.11"

[tool.setuptools.packages.find]
include = ["lib*", "catalysts*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra -q"
```

- [ ] **Step 5: Write `README.md`**

```markdown
# catalyst-tracker

AI Infrastructure Bubble-Stress catalyst tracker. See `docs/source-spec.md` for full design.

## Local dev

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements-dev.txt
    pytest

## Send a test email

Set `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_TO` in env, then:

    python scripts/test_alert.py
```

- [ ] **Step 6: Create venv, install, verify**

Run:
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Expected: `pytest` reports "no tests ran" (exit 5 is acceptable here; exit 0 also fine on some versions). No import errors.

- [ ] **Step 7: Commit**

```bash
git add .gitignore requirements.txt requirements-dev.txt pyproject.toml README.md
git commit -m "chore: bootstrap repo (deps, pytest config, gitignore)"
```

---

## Task 2: `lib/config.py` — watchlists and env loader

**Files:**
- Create: `lib/__init__.py` (empty), `lib/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write `tests/test_config.py`**

```python
import os
import pytest
from lib import config

def test_watchlist_hyperscalers_includes_msft():
    assert config.HYPERSCALERS["MSFT"] == "0000789019"

def test_watchlist_neoclouds_includes_crwv():
    assert config.NEOCLOUDS["CRWV"] == "0001769628"

def test_all_ciks_are_10_digit_strings():
    for d in (config.HYPERSCALERS, config.NEOCLOUDS):
        for ticker, cik in d.items():
            assert isinstance(cik, str) and len(cik) == 10 and cik.isdigit(), (ticker, cik)

def test_require_env_returns_value(monkeypatch):
    monkeypatch.setenv("FOO", "bar")
    assert config.require_env("FOO") == "bar"

def test_require_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("FOO", raising=False)
    with pytest.raises(RuntimeError, match="FOO"):
        config.require_env("FOO")

def test_sec_user_agent_falls_back(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    ua = config.sec_user_agent()
    assert "catalyst-tracker" in ua and "@" in ua
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/test_config.py -v
```
Expected: ImportError or ModuleNotFoundError on `lib.config`.

- [ ] **Step 3: Write `lib/__init__.py` and `lib/config.py`**

`lib/__init__.py`: empty file.

`lib/config.py`:
```python
import os

HYPERSCALERS = {
    "MSFT":  "0000789019",
    "GOOGL": "0001652044",
    "META":  "0001326801",
    "AMZN":  "0001018724",
    "ORCL":  "0001341439",
    "NVDA":  "0001045810",
}

NEOCLOUDS = {
    "CRWV": "0001769628",
    "APLD": "0001144879",
    "IREN": "0001878848",
    "NBIS": "0001513845",
}

def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"required environment variable {name} is not set")
    return v

def sec_user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "catalyst-tracker cyprien0312@gmail.com")
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/test_config.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/__init__.py lib/config.py tests/__init__.py tests/test_config.py
git commit -m "feat(config): watchlists, env loader, SEC user-agent helper"
```
(Create `tests/__init__.py` as empty if not present.)

---

## Task 3: `lib/state.py` — SQLite wrapper

**Files:**
- Create: `lib/state.py`, `state/.gitkeep`
- Test: `tests/test_state.py`

State responsibilities (foundation scope only):
- Open/create a SQLite DB at a configurable path (default `state/tracker.sqlite`).
- Ensure a generic `seen(table_name, key, ts)` table exists; provide `seen(table, key) -> bool` and `mark_seen(table, key)`.
- TTL support on `seen`: `seen(table, key, ttl_seconds=...)` returns False if record older than TTL.
- Provide `connection()` ctx-mgr for catalyst-specific tables created by later plans.

- [ ] **Step 1: Write `tests/test_state.py`**

```python
import time
from lib.state import State

def test_seen_returns_false_before_mark(tmp_path):
    st = State("test", db_path=tmp_path / "t.sqlite")
    assert st.seen("foo", "k1") is False

def test_mark_then_seen_returns_true(tmp_path):
    st = State("test", db_path=tmp_path / "t.sqlite")
    st.mark_seen("foo", "k1")
    assert st.seen("foo", "k1") is True

def test_seen_expires_with_ttl(tmp_path):
    st = State("test", db_path=tmp_path / "t.sqlite")
    st.mark_seen("foo", "k1")
    # Force-age the row
    with st.connection() as c:
        c.execute("UPDATE seen SET ts = ? WHERE table_name=? AND key=?",
                  (int(time.time()) - 100, "foo", "k1"))
    assert st.seen("foo", "k1", ttl_seconds=50) is False
    assert st.seen("foo", "k1", ttl_seconds=500) is True

def test_mark_seen_idempotent(tmp_path):
    st = State("test", db_path=tmp_path / "t.sqlite")
    st.mark_seen("foo", "k1")
    st.mark_seen("foo", "k1")
    assert st.seen("foo", "k1") is True

def test_connection_is_usable_for_custom_tables(tmp_path):
    st = State("test", db_path=tmp_path / "t.sqlite")
    with st.connection() as c:
        c.execute("CREATE TABLE x(a INTEGER PRIMARY KEY)")
        c.execute("INSERT INTO x(a) VALUES (1)")
    with st.connection() as c:
        rows = list(c.execute("SELECT a FROM x"))
    assert rows == [(1,)]
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/test_state.py -v
```
Expected: ModuleNotFoundError on `lib.state`.

- [ ] **Step 3: Write `lib/state.py`**

```python
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = Path("state/tracker.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    table_name TEXT NOT NULL,
    key        TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    PRIMARY KEY(table_name, key)
);
"""

class State:
    def __init__(self, namespace: str, db_path: Path | str = DEFAULT_DB):
        self.namespace = namespace
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    def seen(self, table: str, key: str, ttl_seconds: int | None = None) -> bool:
        with self.connection() as c:
            row = c.execute(
                "SELECT ts FROM seen WHERE table_name=? AND key=?",
                (table, key),
            ).fetchone()
        if row is None:
            return False
        if ttl_seconds is None:
            return True
        return (int(time.time()) - int(row[0])) <= ttl_seconds

    def mark_seen(self, table: str, key: str) -> None:
        with self.connection() as c:
            c.execute(
                "INSERT INTO seen(table_name, key, ts) VALUES(?,?,?) "
                "ON CONFLICT(table_name, key) DO UPDATE SET ts=excluded.ts",
                (table, key, int(time.time())),
            )
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/test_state.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Add `state/.gitkeep` and commit**

```bash
mkdir -p state && touch state/.gitkeep
git add lib/state.py tests/test_state.py state/.gitkeep
git commit -m "feat(state): SQLite wrapper with seen/mark_seen + TTL"
```

---

## Task 4: `lib/notify.py` — Gmail SMTP with dedup

**Files:**
- Create: `lib/notify.py`
- Test: `tests/test_notify.py`

- [ ] **Step 1: Write `tests/test_notify.py`**

```python
from unittest.mock import MagicMock, patch
from lib.notify import send_alert
from lib.state import State

ENV = {
    "GMAIL_USER": "alerts@example.com",
    "GMAIL_APP_PASSWORD": "pw",
    "ALERT_TO": "dest@example.com",
}

@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_sends_email(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items(): monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp = smtp_cls.return_value.__enter__.return_value = MagicMock()
    sent = send_alert("subj", "body", state=st)
    assert sent is True
    smtp.login.assert_called_once_with("alerts@example.com", "pw")
    assert smtp.send_message.called

@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_dedups_within_ttl(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items(): monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp_cls.return_value.__enter__.return_value = MagicMock()
    assert send_alert("subj", "body", state=st) is True
    assert send_alert("subj", "body", state=st) is False  # deduped

@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_sends_when_body_differs(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items(): monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp_cls.return_value.__enter__.return_value = MagicMock()
    assert send_alert("subj", "body A", state=st) is True
    assert send_alert("subj", "body B", state=st) is True

@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_severity_header(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items(): monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp = smtp_cls.return_value.__enter__.return_value = MagicMock()
    send_alert("subj", "body", severity="HIGH", state=st)
    msg = smtp.send_message.call_args.args[0]
    assert msg["X-Catalyst-Severity"] == "HIGH"
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/test_notify.py -v
```
Expected: ModuleNotFoundError on `lib.notify`.

- [ ] **Step 3: Write `lib/notify.py`**

```python
import hashlib
import smtplib
from email.message import EmailMessage

from lib.config import require_env
from lib.state import State

DEDUP_TTL_SECONDS = 7 * 86400

def _fingerprint(subject: str, body: str) -> str:
    return hashlib.sha256(f"{subject}|{body[:500]}".encode()).hexdigest()

def send_alert(subject: str, body: str, severity: str = "MED",
               state: State | None = None) -> bool:
    st = state or State("notify")
    fp = _fingerprint(subject, body)
    if st.seen("alerts_dedup", fp, ttl_seconds=DEDUP_TTL_SECONDS):
        return False

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

    st.mark_seen("alerts_dedup", fp)
    return True
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/test_notify.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/notify.py tests/test_notify.py
git commit -m "feat(notify): Gmail SMTP with SHA-256 dedup and severity header"
```

---

## Task 5: `lib/rate_limit.py` — token bucket

**Files:**
- Create: `lib/rate_limit.py`
- Test: extended into `tests/test_edgar.py` (rate-limit behavior is observed there)

- [ ] **Step 1: Write `lib/rate_limit.py`** (no separate test; covered by edgar test)

```python
import time
from threading import Lock

class TokenBucket:
    """Minimum-spacing rate limiter. Thread-safe."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.monotonic()
```

- [ ] **Step 2: Commit (along with Task 6)** — combined commit at end of edgar task.

---

## Task 6: `lib/edgar.py` — SEC client

**Files:**
- Create: `lib/edgar.py`
- Test: `tests/test_edgar.py`, `tests/fixtures/edgar_submissions_amzn.json`

Edgar client responsibilities (foundation scope):
- `recent_filings(cik, forms=("10-K","10-Q","8-K"), limit=20) -> list[Filing]` reading `https://data.sec.gov/submissions/CIK{cik}.json`.
- `get_filing_text(filing) -> str` fetching primary document HTML, stripping tags to plain text.
- Always send `User-Agent` from `config.sec_user_agent()`.
- Rate-limit via `TokenBucket(0.2)` (≤5 req/s).
- Retry 5xx / connection errors via `tenacity` (3 attempts, exponential backoff).
- `Filing` dataclass: `cik, accession, form, filed_date, primary_document, url`.

- [ ] **Step 1: Write fixture `tests/fixtures/edgar_submissions_amzn.json`**

Minimal shape (matches what `recent_filings` reads):
```json
{
  "cik": "1018724",
  "name": "AMAZON.COM, INC.",
  "filings": {
    "recent": {
      "accessionNumber": ["0001018724-25-000004", "0001018724-24-000999"],
      "form":            ["10-K",                  "8-K"],
      "filingDate":      ["2025-02-07",            "2024-12-15"],
      "primaryDocument": ["amzn-20241231.htm",     "amzn-8k.htm"]
    }
  }
}
```

- [ ] **Step 2: Write `tests/test_edgar.py`**

```python
import json
from pathlib import Path
import responses
from lib.edgar import EdgarClient, Filing

FIX = Path(__file__).parent / "fixtures"

@responses.activate
def test_recent_filings_parses_submissions_json():
    body = (FIX / "edgar_submissions_amzn.json").read_text()
    responses.add(
        responses.GET,
        "https://data.sec.gov/submissions/CIK0001018724.json",
        body=body, status=200, content_type="application/json",
    )
    c = EdgarClient()
    filings = c.recent_filings("0001018724", forms=("10-K", "8-K"), limit=10)
    assert len(filings) == 2
    f0 = filings[0]
    assert isinstance(f0, Filing)
    assert f0.accession == "0001018724-25-000004"
    assert f0.form == "10-K"
    assert f0.filed_date == "2025-02-07"
    assert f0.primary_document == "amzn-20241231.htm"
    assert f0.cik == "0001018724"
    assert f0.url.endswith("/000101872425000004/amzn-20241231.htm")

@responses.activate
def test_recent_filings_filters_by_form():
    body = (FIX / "edgar_submissions_amzn.json").read_text()
    responses.add(
        responses.GET,
        "https://data.sec.gov/submissions/CIK0001018724.json",
        body=body, status=200,
    )
    c = EdgarClient()
    only_10k = c.recent_filings("0001018724", forms=("10-K",))
    assert [f.form for f in only_10k] == ["10-K"]

@responses.activate
def test_get_filing_text_strips_html():
    f = Filing(
        cik="0001018724",
        accession="0001018724-25-000004",
        form="10-K",
        filed_date="2025-02-07",
        primary_document="amzn-20241231.htm",
        url="https://www.sec.gov/Archives/edgar/data/1018724/000101872425000004/amzn-20241231.htm",
    )
    responses.add(
        responses.GET, f.url,
        body="<html><body><p>Hello <b>world</b></p><script>x()</script></body></html>",
        status=200,
    )
    c = EdgarClient()
    text = c.get_filing_text(f)
    assert "Hello world" in text
    assert "x()" not in text  # script content stripped

@responses.activate
def test_user_agent_header_is_sent(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "catalyst-tracker test@example.com")
    body = (FIX / "edgar_submissions_amzn.json").read_text()
    responses.add(
        responses.GET,
        "https://data.sec.gov/submissions/CIK0001018724.json",
        body=body, status=200,
    )
    c = EdgarClient()
    c.recent_filings("0001018724")
    sent = responses.calls[0].request
    assert sent.headers["User-Agent"] == "catalyst-tracker test@example.com"
```

- [ ] **Step 3: Run — must fail**

```bash
pytest tests/test_edgar.py -v
```
Expected: ModuleNotFoundError on `lib.edgar`.

- [ ] **Step 4: Write `lib/edgar.py`**

```python
import re
from dataclasses import dataclass
from typing import Iterable

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from lib.config import sec_user_agent
from lib.rate_limit import TokenBucket

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary}"

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.I | re.S)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.I | re.S)
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Filing:
    cik: str
    accession: str
    form: str
    filed_date: str
    primary_document: str
    url: str


def _strip_html(html: str) -> str:
    s = _SCRIPT_RE.sub(" ", html)
    s = _STYLE_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


class EdgarClient:
    def __init__(self, min_interval: float = 0.2):
        self._bucket = TokenBucket(min_interval)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = sec_user_agent()
        self._session.headers["Accept-Encoding"] = "gzip, deflate"

    @retry(reraise=True, stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=2, min=2, max=8),
           retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)))
    def _get(self, url: str) -> requests.Response:
        self._bucket.wait()
        r = self._session.get(url, timeout=30)
        r.raise_for_status()
        return r

    def recent_filings(self, cik: str, forms: Iterable[str] = ("10-K", "10-Q", "8-K"),
                       limit: int = 20) -> list[Filing]:
        url = SUBMISSIONS_URL.format(cik=cik)
        data = self._get(url).json()
        rec = data["filings"]["recent"]
        accs = rec["accessionNumber"]
        out: list[Filing] = []
        wanted = set(forms)
        for i, acc in enumerate(accs):
            form = rec["form"][i]
            if form not in wanted:
                continue
            primary = rec["primaryDocument"][i]
            cik_int = str(int(cik))
            acc_nodash = acc.replace("-", "")
            out.append(Filing(
                cik=cik,
                accession=acc,
                form=form,
                filed_date=rec["filingDate"][i],
                primary_document=primary,
                url=ARCHIVE_URL.format(cik_int=cik_int, acc_nodash=acc_nodash, primary=primary),
            ))
            if len(out) >= limit:
                break
        return out

    def get_filing_text(self, filing: Filing) -> str:
        return _strip_html(self._get(filing.url).text)
```

- [ ] **Step 5: Run — must pass**

```bash
pytest tests/test_edgar.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add lib/rate_limit.py lib/edgar.py tests/test_edgar.py tests/fixtures/edgar_submissions_amzn.json
git commit -m "feat(edgar): SEC client with rate limiting, retries, HTML→text"
```

---

## Task 7: `catalysts/base.py` — `Alert` + `CatalystBase`

**Files:**
- Create: `catalysts/__init__.py` (empty), `catalysts/base.py`
- Test: `tests/test_base.py`

- [ ] **Step 1: Write `tests/test_base.py`**

```python
import pytest
from catalysts.base import Alert, CatalystBase

def test_alert_dataclass_fields():
    a = Alert(catalyst="C1", severity="HIGH", subject="s", body="b")
    assert a.catalyst == "C1" and a.severity == "HIGH"
    assert a.subject == "s" and a.body == "b"

def test_alert_severity_validated():
    with pytest.raises(ValueError):
        Alert(catalyst="C1", severity="WHATEVER", subject="s", body="b")

def test_catalystbase_subclass_must_implement_run():
    class Empty(CatalystBase):
        name = "Empty"
    with pytest.raises(TypeError):
        Empty()

def test_catalystbase_subclass_runs():
    class Mine(CatalystBase):
        name = "Mine"
        def run(self):
            return [Alert("CX", "MED", "subj", "body")]
    out = Mine().run()
    assert len(out) == 1 and out[0].subject == "subj"
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/test_base.py -v
```
Expected: ModuleNotFoundError on `catalysts.base`.

- [ ] **Step 3: Write `catalysts/__init__.py` (empty) and `catalysts/base.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

VALID_SEVERITIES = ("LOG", "MED", "HIGH", "CRITICAL")


@dataclass(frozen=True)
class Alert:
    catalyst: str
    severity: str
    subject: str
    body: str

    def __post_init__(self):
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of {VALID_SEVERITIES}, got {self.severity!r}")


class CatalystBase(ABC):
    name: str = ""

    @abstractmethod
    def run(self) -> list[Alert]:
        ...
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/test_base.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add catalysts/__init__.py catalysts/base.py tests/test_base.py
git commit -m "feat(catalysts): CatalystBase ABC + Alert dataclass"
```

---

## Task 8: `scripts/test_alert.py` — manual SMTP smoke test

**Files:**
- Create: `scripts/test_alert.py`

This is not unit-tested (it intentionally calls real SMTP). It's the artifact the user runs once to confirm Gmail credentials work.

- [ ] **Step 1: Write `scripts/test_alert.py`**

```python
"""Send a single test email to verify Gmail SMTP credentials.

Usage:
    GMAIL_USER=... GMAIL_APP_PASSWORD=... ALERT_TO=... \
        python scripts/test_alert.py
"""
import sys
from lib.notify import send_alert
from lib.state import State

def main() -> int:
    st = State("smoke")
    # Bypass dedup by including a fresh timestamp in the body.
    import time
    body = f"catalyst-tracker smoke test at unix={int(time.time())}"
    ok = send_alert("[OPS-TEST] catalyst-tracker SMTP smoke", body, severity="MED", state=st)
    print("sent" if ok else "deduped")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Commit**

```bash
git add scripts/test_alert.py
git commit -m "feat(scripts): test_alert.py for SMTP smoke test"
```

- [ ] **Step 3: Pause for manual verification**

Before declaring Foundation complete, the user runs:
```bash
. .venv/bin/activate
export GMAIL_USER=cyprien0312@gmail.com
export GMAIL_APP_PASSWORD=...   # 16 chars, no spaces
export ALERT_TO=cyprien0312@gmail.com
python scripts/test_alert.py
```
Expected: prints `sent`, an email arrives in the `ALERT_TO` inbox with subject starting `[OPS-TEST]`.

If this fails, do NOT proceed to Catalyst 1; debug SMTP first.

---

## Task 9: Final foundation check

- [ ] **Step 1: Run the full suite**

```bash
pytest -v
```
Expected: all tests pass (18 across the foundation tasks).

- [ ] **Step 2: Verify import surface**

```bash
python -c "from lib.config import HYPERSCALERS, NEOCLOUDS, require_env, sec_user_agent; from lib.state import State; from lib.notify import send_alert; from lib.edgar import EdgarClient, Filing; from catalysts.base import Alert, CatalystBase; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Confirm clean tree**

```bash
git status
```
Expected: clean (only `state/tracker.sqlite` from the smoke run might be untracked — leave it gitignored once we add a per-catalyst commit step; for now the empty `state/.gitkeep` is what's tracked).

Foundation complete. Next: `2026-05-11-catalyst-1-depreciation.md`.

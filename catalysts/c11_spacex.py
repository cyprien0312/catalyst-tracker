"""Catalyst 11 — SpaceX IPO unlock / passive-flow stress.

SpaceX (SPCX, IPO 2026-06-12) is the live specimen of late-cycle index
mechanics: fast-tracked into the Nasdaq-100 at ~0.75% weight (≈$6bn of
forced passive buying) while ~97% of its 13.08bn shares unlock in rolling
tranches over the twelve months after listing. Passive inflow vs. unlock
supply is the cleanest single-name read on whether index plumbing can
absorb mega-IPO distribution — the same dynamic that will replay for the
OpenAI/Anthropic listings this tracker cares about.

Three legs:

1. **Unlock calendar** (deterministic) — tranche dates estimated from the
   S-1/424B4 lock-up terms. ⚠️ ESTIMATED: earnings-linked tranches shift
   with reporting dates; the authoritative source is the prospectus on
   EDGAR. Alerts fire LEAD_DAYS before each tranche.
2. **News flow** (Google News RSS, same substrate as C3/C6) — proximity
   classifier for unlock / insider-selling / secondary-offering language.
3. **ETF holdings diff** (daily issuer CSVs; ARK publishes freshest) —
   share-count swings in funds that hold SPCX. A large cut is live
   distribution; a large add is passive absorption.
"""
from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import requests

from catalysts.base import Alert, CatalystBase
from lib.explanations import append_context
from lib.log import get_logger
from lib.rss import Entry, fetch_many
from lib.state import State

log = get_logger(__name__)

TOTAL_SHARES_BN = 130.76  # 亿股 — total shares outstanding per S-1-derived table

# ---------------------------------------------------------------------------
# Leg 1 — unlock calendar
# ---------------------------------------------------------------------------

LEAD_DAYS = 7  # alert this many days before a tranche


@dataclass(frozen=True)
class Tranche:
    label: str            # human label, e.g. "Day 180"
    est_date: str         # ISO date, ESTIMATED for earnings-linked tranches
    release_bn: float     # shares released this tranche, 亿股
    cumulative_pct: float # % of total shares free-floating after this tranche
    estimated: bool = False  # True when the date depends on an earnings print


# Derived from the S-1/424B4 lock-up terms (community reconstruction,
# cross-checked against IPO date 2026-06-12). Earnings-linked rows carry
# estimated=True — re-verify against EDGAR when the reporting date lands.
UNLOCK_SCHEDULE: tuple[Tranche, ...] = (
    Tranche("Q2'26 earnings +2td",       "2026-07-31",  9.1, 11.2, estimated=True),
    Tranche("Price ≥130% tranche",       "2026-08-03",  4.6, 14.7, estimated=True),
    Tranche("Day 70",                    "2026-08-21",  3.2, 17.2),
    Tranche("Day 90",                    "2026-09-10",  3.2, 19.6),
    Tranche("Day 91",                    "2026-09-11",  0.6, 20.0),
    Tranche("Day 105",                   "2026-09-25",  3.3, 22.6),
    Tranche("Day 120",                   "2026-10-10",  3.3, 25.1),
    Tranche("Day 135",                   "2026-10-25",  3.3, 27.6),
    Tranche("Q3'26 earnings +2td",       "2026-10-30", 13.0, 37.5, estimated=True),
    Tranche("Day 180",                   "2026-12-09",  3.3, 40.0),
    Tranche("Q4'26 earnings",            "2027-01-29",  3.5, 42.7, estimated=True),
    Tranche("Day 280",                   "2027-03-19",  1.8, 44.1),
    Tranche("Q1'27 earnings",            "2027-04-30",  3.5, 46.8, estimated=True),
    Tranche("Day 340",                   "2027-05-18",  1.8, 48.1),
    Tranche("Day 366 — Musk 6.05bn full unlock", "2027-06-13", 64.0, 97.1),
    Tranche("Q2'27 earnings",            "2027-06-30",  3.5, 99.7, estimated=True),
)

# Single-tranche size → severity. The Day-366 Musk tranche (64亿 ≈ 49% of
# the company) is its own category.
TRANCHE_CRITICAL_BN = 30.0
TRANCHE_HIGH_BN = 8.0


def tranche_severity(t: Tranche) -> str:
    if t.release_bn >= TRANCHE_CRITICAL_BN:
        return "CRITICAL"
    if t.release_bn >= TRANCHE_HIGH_BN:
        return "HIGH"
    return "MED"


def upcoming_tranches(today: date, lead_days: int = LEAD_DAYS) -> list[Tranche]:
    """Tranches whose estimated date falls within [today, today+lead_days]."""
    horizon = today + timedelta(days=lead_days)
    out = []
    for t in UNLOCK_SCHEDULE:
        d = datetime.strptime(t.est_date, "%Y-%m-%d").date()
        if today <= d <= horizon:
            out.append(t)
    return out


def _render_tranche_body(t: Tranche, sev: str, today: date) -> str:
    d = datetime.strptime(t.est_date, "%Y-%m-%d").date()
    est = " (ESTIMATED — earnings-linked, re-verify on EDGAR)" if t.estimated else ""
    return (
        f"Severity:   {sev}\n"
        f"Tranche:    {t.label}\n"
        f"Date:       {t.est_date}{est}  ({(d - today).days} day(s) out)\n"
        f"Release:    {t.release_bn:.1f}亿 shares "
        f"({t.release_bn / TOTAL_SHARES_BN * 100:.1f}% of shares outstanding)\n"
        f"Cumulative: {t.cumulative_pct:.1f}% of total unlocked after this tranche\n\n"
        f"Lock-up terms per the SPCX S-1/424B4 (EDGAR); dates for earnings-linked\n"
        f"tranches are estimates and shift with the reporting calendar.\n"
    )


# ---------------------------------------------------------------------------
# Leg 2 — news flow
# ---------------------------------------------------------------------------

DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?q=SpaceX+OR+SPCX+stock+when:1d&hl=en-US&gl=US&ceid=US:en",
]

PROXIMITY_WINDOW = 120  # same FP guard as C3/C6

_SUBJECT_RE = re.compile(r"\b(spacex|spcx|space\s+exploration\s+tech)\b", re.I)

# Launch-coverage noise guard: routine mission news is not a market signal.
_MISSION_NOISE_RE = re.compile(
    r"\b(launch(?:es|ed)?\s+(?:\d+|another|new)\s+(?:starlink\s+)?satellites?|"
    r"landing|booster|starship\s+test|crew-\d+|astronauts?|docking|"
    r"space\s+station|cape\s+canaveral)\b",
    re.I,
)

CRITICAL_TOKENS = (
    r"\bsecondary\s+offering\b",
    r"\binsiders?\s+(?:dump|flood|rush\s+to\s+sell)\b",
    r"\bmusk\s+(?:sells?|sold|to\s+sell)\b",
    r"\block-?up\s+(?:waiv|releas)(?:er|ed|e)\b",
)

HIGH_TOKENS = (
    r"\block-?ups?\s+(?:expir|end|lift)\w*\b",
    r"\bunlock\w*\b",
    r"\bshare\s+sales?\b",
    r"\binsider\s+selling\b",
    r"\bdilut(?:ion|ive)\b",
    r"\bfloat\s+(?:expand|increas|doubl)\w*\b",
)

MED_TOKENS = (
    r"\bnasdaq-?\s?100\b",
    r"\bindex\s+(?:inclusion|add(?:ition)?|weight)\b",
    r"\bpassive\s+(?:buy|flow|demand)\w*\b",
    r"\betf\s+(?:buy|inflow)\w*\b",
    r"\bprice\s+target\b",
)

_TIERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("CRITICAL", "C11_INSIDER_SUPPLY", CRITICAL_TOKENS),
    ("HIGH", "C11_UNLOCK_NEWS", HIGH_TOKENS),
    ("MED", "C11_INDEX_FLOW", MED_TOKENS),
)


def _near_subject(text: str, token_pattern: str) -> bool:
    subject_spans = [m.span() for m in _SUBJECT_RE.finditer(text)]
    if not subject_spans:
        return False
    for tm in re.finditer(token_pattern, text, flags=re.I):
        ts, te = tm.span()
        for ss, se in subject_spans:
            if ts >= se:
                gap = ts - se
            elif ss >= te:
                gap = ss - te
            else:
                gap = 0
            if gap <= PROXIMITY_WINDOW:
                return True
    return False


def classify(text: str) -> tuple[str, str] | None:
    """(severity, signal_kind) if a SpaceX mention pairs with a tier token
    nearby; routine mission coverage is rejected outright."""
    if not _SUBJECT_RE.search(text):
        return None
    if _MISSION_NOISE_RE.search(text) and not any(
        re.search(p, text, re.I) for _, _, toks in _TIERS for p in toks
    ):
        return None
    for sev, kind, tokens in _TIERS:
        for pat in tokens:
            if _near_subject(text, pat):
                return sev, kind
    return None


def _render_news_body(entry: Entry, severity: str) -> str:
    return (
        f"Severity:  {severity}\n"
        f"Feed:      {entry.feed_url}\n"
        f"Published: {entry.published}\n"
        f"Link:      {entry.link}\n\n"
        f"{entry.title}\n\n"
        f"{entry.summary}\n"
    )


# ---------------------------------------------------------------------------
# Leg 3 — ETF holdings diff
# ---------------------------------------------------------------------------

# fund label -> daily holdings CSV. ARK's endpoints are stable and fresh
# (verified 2026-07-11: ARKQ holds SPCX, dated same-week). Override or extend
# via env C11_ETF_CSVS="FUND=url,FUND2=url2".
DEFAULT_ETF_CSVS: dict[str, str] = {
    "ARKQ": ("https://assets.ark-funds.com/fund-documents/funds-etf-csv/"
             "ARK_AUTONOMOUS_TECH._%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv"),
}

_SPCX_CUSIP_PREFIX = "84615Q"
ETF_SWING_PCT = 20.0  # |Δshares| ≥ this % vs prior snapshot → alert


def _etf_csvs_from_env() -> dict[str, str]:
    raw = os.environ.get("C11_ETF_CSVS", "").strip()
    if not raw:
        return dict(DEFAULT_ETF_CSVS)
    out: dict[str, str] = {}
    for part in raw.split(","):
        if "=" in part:
            fund, url = part.split("=", 1)
            out[fund.strip()] = url.strip()
    return out


def parse_holdings_csv(text: str) -> dict | None:
    """Extract the SPCX row from an issuer holdings CSV.

    Returns {"date": iso, "shares": float, "weight_pct": float} or None.
    Matches on CUSIP prefix first (robust to ticker suffixes like 'SPCX UQ'),
    ticker second."""
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        norm = {(k or "").strip().lower(): (v or "").strip()
                for k, v in row.items()}
        cusip = norm.get("cusip", "")
        ticker = norm.get("ticker", "").upper()
        if not (cusip.startswith(_SPCX_CUSIP_PREFIX) or
                ticker.split()[0:1] == ["SPCX"]):
            continue
        try:
            shares = float(norm.get("shares", "").replace(",", "").replace('"', ""))
        except ValueError:
            return None
        weight = norm.get("weight (%)", norm.get("weight", "")).replace("%", "")
        try:
            weight_pct = float(weight)
        except ValueError:
            weight_pct = 0.0
        raw_date = norm.get("date", "")
        try:
            iso = datetime.strptime(raw_date, "%m/%d/%Y").date().isoformat()
        except ValueError:
            iso = raw_date or date.today().isoformat()
        return {"date": iso, "shares": shares, "weight_pct": weight_pct}
    return None


def _ensure_table(state: State) -> None:
    with state.connection() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS c11_etf (
                fund TEXT,
                snapshot_date TEXT,
                shares REAL,
                weight_pct REAL,
                PRIMARY KEY(fund, snapshot_date)
            )
        """)


def _store_snapshot(state: State, fund: str, snap: dict) -> None:
    with state.connection() as c:
        c.execute(
            "INSERT INTO c11_etf(fund, snapshot_date, shares, weight_pct) "
            "VALUES(?,?,?,?) "
            "ON CONFLICT(fund, snapshot_date) DO UPDATE SET "
            "shares=excluded.shares, weight_pct=excluded.weight_pct",
            (fund, snap["date"], snap["shares"], snap["weight_pct"]),
        )


def _prior_snapshot(state: State, fund: str, current_date: str) -> dict | None:
    with state.connection() as c:
        row = c.execute(
            "SELECT snapshot_date, shares, weight_pct FROM c11_etf "
            "WHERE fund=? AND snapshot_date<? ORDER BY snapshot_date DESC LIMIT 1",
            (fund, current_date),
        ).fetchone()
    if not row:
        return None
    return {"date": row[0], "shares": float(row[1]), "weight_pct": float(row[2])}


def diff_snapshots(prior: dict | None, current: dict) -> tuple[str, str] | None:
    """(severity, direction) when the share count swings ≥ ETF_SWING_PCT.

    Cuts are the distribution signal (HIGH); adds are absorption (MED)."""
    if prior is None or prior["shares"] <= 0:
        return None
    change_pct = (current["shares"] - prior["shares"]) / prior["shares"] * 100
    if change_pct <= -ETF_SWING_PCT:
        return "HIGH", f"cut {abs(change_pct):.1f}%"
    if change_pct >= ETF_SWING_PCT:
        return "MED", f"added {change_pct:.1f}%"
    return None


def _render_etf_body(fund: str, prior: dict, current: dict,
                     sev: str, direction: str) -> str:
    return (
        f"Severity: {sev}\n"
        f"Fund:     {fund}\n"
        f"Change:   {direction} "
        f"({prior['shares']:,.0f} → {current['shares']:,.0f} shares)\n"
        f"Weight:   {prior['weight_pct']:.2f}% → {current['weight_pct']:.2f}%\n"
        f"Dates:    {prior['date']} → {current['date']}\n\n"
        f"Source: issuer daily holdings CSV.\n"
    )


# ---------------------------------------------------------------------------
# Catalyst
# ---------------------------------------------------------------------------

class Catalyst11(CatalystBase):
    name = "SpaceX IPO Unlock / Passive Flows"

    def __init__(self, state: State | None = None,
                 feeds: list[str] | None = None,
                 etf_csvs: dict[str, str] | None = None,
                 today: date | None = None):
        self._state = state or State("c11")
        self._feeds = feeds if feeds is not None else DEFAULT_FEEDS
        self._etf_csvs = etf_csvs if etf_csvs is not None else _etf_csvs_from_env()
        self._today = today or date.today()

    def run(self) -> list[Alert]:
        alerts: list[Alert] = []
        alerts += self._run_calendar()
        alerts += self._run_news()
        alerts += self._run_etf()
        return alerts

    # -- leg 1
    def _run_calendar(self) -> list[Alert]:
        alerts: list[Alert] = []
        for t in upcoming_tranches(self._today):
            key = f"{t.est_date}:{t.label}"
            if self._state.seen("c11_lockup", key):
                continue
            sev = tranche_severity(t)
            body = append_context(
                _render_tranche_body(t, sev, self._today), "C11",
                "C11_UNLOCK_UPCOMING",
                ticker="SPCX",
                numbers={"release_bn": t.release_bn,
                         "cumulative_pct": t.cumulative_pct},
            )
            alerts.append(Alert(
                catalyst="C11", severity=sev,
                subject=f"[C11-{sev}] SPCX unlock in ≤{LEAD_DAYS}d: {t.label} "
                        f"({t.release_bn:.1f}亿 shares)",
                body=body,
            ))
            self._state.mark_seen("c11_lockup", key)
        return alerts

    # -- leg 2
    def _run_news(self) -> list[Alert]:
        alerts: list[Alert] = []
        for entry in fetch_many(self._feeds, self._state):
            text = f"{entry.title}\n{entry.summary}"
            hit = classify(text)
            if not hit:
                continue
            sev, kind = hit
            body = append_context(
                _render_news_body(entry, sev), "C11", kind,
                snippet=text[:4000],
            )
            alerts.append(Alert(
                catalyst="C11", severity=sev,
                subject=f"[C11-{sev}] {entry.title[:120]}",
                body=body,
            ))
        return alerts

    # -- leg 3
    def _run_etf(self) -> list[Alert]:
        alerts: list[Alert] = []
        _ensure_table(self._state)
        for fund, url in self._etf_csvs.items():
            try:
                resp = requests.get(url, timeout=30,
                                    headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
            except requests.RequestException as e:
                log.warning("c11: ETF CSV fetch failed for %s: %s", fund, e)
                continue
            snap = parse_holdings_csv(resp.text)
            if snap is None:
                # Position gone entirely is itself a signal — but only if we
                # previously had one (avoid alerting on funds that never held).
                prior = _prior_snapshot(state=self._state, fund=fund,
                                        current_date="9999-99-99")
                if prior and prior["shares"] > 0:
                    key = f"exit:{fund}:{prior['date']}"
                    if not self._state.seen("c11_etf_exit", key):
                        body = append_context(
                            f"Severity: HIGH\nFund: {fund}\n"
                            f"SPCX no longer appears in the holdings file "
                            f"(last seen {prior['date']}, "
                            f"{prior['shares']:,.0f} shares).\n",
                            "C11", "C11_ETF_FLOW", ticker="SPCX",
                        )
                        alerts.append(Alert(
                            catalyst="C11", severity="HIGH",
                            subject=f"[C11-HIGH] {fund} dropped SPCX from holdings",
                            body=body,
                        ))
                        self._state.mark_seen("c11_etf_exit", key)
                continue
            prior = _prior_snapshot(self._state, fund, snap["date"])
            _store_snapshot(self._state, fund, snap)
            hit = diff_snapshots(prior, snap)
            if not hit:
                continue
            sev, direction = hit
            key = f"{fund}:{prior['date']}->{snap['date']}"
            if self._state.seen("c11_etf_diff", key):
                continue
            body = append_context(
                _render_etf_body(fund, prior, snap, sev, direction),
                "C11", "C11_ETF_FLOW", ticker="SPCX",
                numbers={"prior_shares": prior["shares"],
                         "current_shares": snap["shares"]},
            )
            alerts.append(Alert(
                catalyst="C11", severity=sev,
                subject=f"[C11-{sev}] {fund} SPCX position {direction}",
                body=body,
            ))
            self._state.mark_seen("c11_etf_diff", key)
        return alerts


def _main(argv: list[str] | None = None) -> int:
    from catalysts.base import run_cli

    def _factory(args):
        return Catalyst11()

    return run_cli(_factory,
                   description="Catalyst 11: SpaceX IPO unlock / passive flows",
                   argv=argv)


if __name__ == "__main__":
    raise SystemExit(_main())

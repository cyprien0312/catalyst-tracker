"""Catalyst 4 — Hyperscaler Capex Guidance Cuts."""
from __future__ import annotations

import re

from catalysts.base import Alert, CatalystBase
from lib.config import HYPERSCALERS
from lib.edgar import EdgarClient
from lib.log import get_logger
from lib.state import State
from lib.xbrl import company_concept, quarterly_only, compute_ttm

log = get_logger(__name__)

CAPEX_CONCEPT = "PaymentsToAcquirePropertyPlantAndEquipment"
OCF_CONCEPT = "NetCashProvidedByUsedInOperatingActivities"

RATIO_CROSS_THRESHOLD = 1.10   # 110%
RATIO_JUMP_PP = 0.15           # +15 percentage points QoQ

TRANSCRIPT_PATTERNS = [
    ("DISCIPLINED_CAPEX",
     r"(more disciplined|moderating|tempered|slower pace)[^.]{0,60}(capex|capital expenditure|spend|invest)", "HIGH"),
    ("REDUCED_FUTURE_CAPITAL",
     r"(reduc|cut|lower|trim)[^.]{0,30}(202[6-9]) capital", "CRITICAL"),
]
_COMPILED_TX = [(k, re.compile(p, re.I | re.S), s) for k, p, s in TRANSCRIPT_PATTERNS]


def _ensure_table(state: State) -> None:
    with state.connection() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS c4_xbrl (
                cik TEXT,
                period_end TEXT,
                capex_ttm REAL,
                ocf_ttm REAL,
                ratio REAL,
                PRIMARY KEY(cik, period_end)
            )
        """)
        # Migration: add fcf_ttm column if missing.
        cols = [r[1] for r in c.execute("PRAGMA table_info(c4_xbrl)").fetchall()]
        if "fcf_ttm" not in cols:
            try:
                c.execute("ALTER TABLE c4_xbrl ADD COLUMN fcf_ttm REAL")
            except Exception:
                pass


def _prior_state(state: State, cik: str, current_end: str) -> tuple[float | None, float | None]:
    """Return (prior_ratio, prior_fcf) for the most recent earlier snapshot."""
    with state.connection() as c:
        row = c.execute(
            "SELECT ratio, fcf_ttm FROM c4_xbrl WHERE cik=? AND period_end<? "
            "ORDER BY period_end DESC LIMIT 1",
            (cik, current_end),
        ).fetchone()
    if not row:
        return None, None
    prior_ratio = float(row[0]) if row[0] is not None else None
    prior_fcf = float(row[1]) if row[1] is not None else None
    return prior_ratio, prior_fcf


def _store_snapshot(state: State, cik: str, end: str, capex_ttm: float, ocf_ttm: float, ratio: float, fcf_ttm: float) -> None:
    with state.connection() as c:
        c.execute(
            "INSERT INTO c4_xbrl(cik, period_end, capex_ttm, ocf_ttm, ratio, fcf_ttm) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(cik, period_end) DO UPDATE SET "
            "capex_ttm=excluded.capex_ttm, ocf_ttm=excluded.ocf_ttm, ratio=excluded.ratio, fcf_ttm=excluded.fcf_ttm",
            (cik, end, capex_ttm, ocf_ttm, ratio, fcf_ttm),
        )


class Catalyst4(CatalystBase):
    name = "Hyperscaler Capex Guidance Cuts"

    def __init__(self, edgar: EdgarClient | None = None, state: State | None = None,
                 watchlist: dict[str, str] | None = None):
        self._edgar = edgar or EdgarClient()
        self._state = state or State("c4")
        self._watchlist = watchlist if watchlist is not None else HYPERSCALERS
        _ensure_table(self._state)

    def _evaluate_company(self, ticker: str, cik: str) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            capex_pts = quarterly_only(company_concept(self._edgar, cik, CAPEX_CONCEPT))
            ocf_pts = quarterly_only(company_concept(self._edgar, cik, OCF_CONCEPT))
        except Exception:
            log.exception("xbrl fetch failed for %s", ticker)
            return alerts
        capex_ttm = compute_ttm(capex_pts)
        ocf_ttm = compute_ttm(ocf_pts)
        if capex_ttm is None or ocf_ttm is None or ocf_ttm == 0:
            return alerts
        ratio = capex_ttm / ocf_ttm
        end = capex_pts[-1].end
        fcf = ocf_ttm - capex_ttm

        prior, prior_fcf = _prior_state(self._state, cik, end)
        _store_snapshot(self._state, cik, end, capex_ttm, ocf_ttm, ratio, fcf)

        # FCF negative transition trigger: prior FCF was non-negative, current is negative.
        if fcf < 0 and prior_fcf is not None and prior_fcf >= 0:
            key = f"c4_fcf_neg|{cik}|{end}"
            if not self._state.seen("c4_signals", key):
                self._state.mark_seen("c4_signals", key)
                alerts.append(Alert(
                    catalyst="C4", severity="HIGH",
                    subject=f"[C4-HIGH] {ticker}: TTM FCF turned negative ({fcf/1e9:.1f}B as of {end})",
                    body=(
                        f"Ticker:    {ticker}\nPeriod:    TTM ending {end}\n"
                        f"Capex TTM: ${capex_ttm/1e9:.2f}B\nOCF TTM:   ${ocf_ttm/1e9:.2f}B\n"
                        f"FCF TTM:   ${fcf/1e9:.2f}B\nRatio:     {ratio*100:.1f}%\n"
                    ),
                ))

        # Ratio threshold cross: must have a prior observation strictly below threshold.
        if prior is not None and prior < RATIO_CROSS_THRESHOLD and ratio >= RATIO_CROSS_THRESHOLD:
            key = f"c4_ratio_cross|{cik}|{end}"
            if not self._state.seen("c4_signals", key):
                self._state.mark_seen("c4_signals", key)
                alerts.append(Alert(
                    catalyst="C4", severity="HIGH",
                    subject=f"[C4-HIGH] {ticker}: TTM Capex/OCF crossed {ratio*100:.0f}% (was {prior*100:.0f}%)",
                    body=(
                        f"Ticker:    {ticker}\nPeriod:    TTM ending {end}\n"
                        f"Capex TTM: ${capex_ttm/1e9:.2f}B\nOCF TTM:   ${ocf_ttm/1e9:.2f}B\n"
                        f"Ratio:     {ratio*100:.1f}% (prior {prior*100:.1f}%)\n"
                    ),
                ))

        # QoQ jump
        if prior is not None and (ratio - prior) >= RATIO_JUMP_PP:
            key = f"c4_ratio_jump|{cik}|{end}"
            if not self._state.seen("c4_signals", key):
                self._state.mark_seen("c4_signals", key)
                alerts.append(Alert(
                    catalyst="C4", severity="MED",
                    subject=f"[C4-MED] {ticker}: Capex/OCF jumped {(ratio-prior)*100:.0f}pp",
                    body=(
                        f"Ticker:    {ticker}\nPeriod:    TTM ending {end}\n"
                        f"Ratio:     {ratio*100:.1f}% (was {prior*100:.1f}%)\n"
                    ),
                ))
        return alerts

    def run(self) -> list[Alert]:
        alerts: list[Alert] = []
        for ticker, cik in self._watchlist.items():
            alerts.extend(self._evaluate_company(ticker, cik))
        return alerts


def _main(argv: list[str] | None = None) -> int:
    import argparse
    from lib.notify import send_alert
    p = argparse.ArgumentParser(description="Catalyst 4: Capex/OCF")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    alerts = Catalyst4().run()
    if not alerts:
        print("c4: no alerts")
        return 0
    for a in alerts:
        if args.dry_run:
            print("=" * 72); print(a.subject); print(a.body)
        else:
            send_alert(a.subject, a.body, severity=a.severity)
    print(f"c4: {len(alerts)} alert(s) {'printed' if args.dry_run else 'emailed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

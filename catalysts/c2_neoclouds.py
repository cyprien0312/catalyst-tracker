"""Catalyst 2 — Neocloud distress detector.

Sources: SEC 10-K/10-Q text scan + 8-K item codes + price-crash signal.
Bond prices and short interest are deferred (see lib/finra.py).
"""
from __future__ import annotations

import re

from catalysts.base import Alert, CatalystBase
from lib.config import NEOCLOUDS
from lib.edgar import EdgarClient, Filing
from lib.prices import stock_crash
from lib.state import State


PATTERNS: list[tuple[str, str, str]] = [
    ("GOING_CONCERN",
     r"substantial\s+doubt[^.]{0,80}going\s+concern", "CRITICAL"),
    ("COVENANT_DISTRESS",
     r"covenant\s+(breach|default|waiver|amendment)", "HIGH"),
    ("MATERIAL_ADVERSE",
     r"material\s+adverse\s+(change|effect)[^.]{0,80}(liquidity|debt|going|covenant)", "HIGH"),
]
_COMPILED = [(k, re.compile(p, re.I | re.S), s) for k, p, s in PATTERNS]

# 8-K item codes that signal distress.
DISTRESS_ITEMS = {
    "2.04": ("CRITICAL", "Triggering Event Accelerating Direct Financial Obligation"),
    "4.02": ("CRITICAL", "Non-Reliance on Previously Issued Financial Statements"),
    "1.03": ("CRITICAL", "Bankruptcy or Receivership"),
}

_SEVERITY_ORDER = {"LOG": 0, "MED": 1, "HIGH": 2, "CRITICAL": 3}


def _max_sev(sevs: list[str]) -> str:
    return max(sevs, key=lambda s: _SEVERITY_ORDER[s])


def scan_text(text: str) -> list[dict]:
    out: list[dict] = []
    for key, rx, sev in _COMPILED:
        m = rx.search(text)
        if m:
            out.append({"key": key, "severity": sev, "snippet": m.group(0)[:240]})
    return out


def _render_filing_body(ticker: str, filing: Filing, hits: list[dict]) -> str:
    lines = [
        f"Ticker:    {ticker}",
        f"Form:      {filing.form}",
        f"Filed:     {filing.filed_date}",
        f"Accession: {filing.accession}",
        f"URL:       {filing.url}",
        "",
        "Hits:",
    ]
    for h in hits:
        snip = h["snippet"].replace("\n", " ")
        lines.append(f"- {h['key']} ({h['severity']}): {snip}")
    return "\n".join(lines)


def _render_8k_body(ticker: str, filing: Filing, items: list[str]) -> str:
    lines = [
        f"Ticker:    {ticker}",
        f"Form:      8-K",
        f"Filed:     {filing.filed_date}",
        f"Accession: {filing.accession}",
        f"URL:       {filing.url}",
        "",
        "Distress items present:",
    ]
    for it in items:
        sev, label = DISTRESS_ITEMS[it]
        lines.append(f"- Item {it} ({sev}): {label}")
    return "\n".join(lines)


def _render_crash_body(ticker: str, c: dict) -> str:
    return (
        f"Ticker:    {ticker}\n"
        f"Date:      {c['date']}\n"
        f"Close:     {c['close']:.2f} (prior {c['prior_close']:.2f})\n"
        f"Change:    {c['change_pct']*100:.1f}%\n"
        f"Volume:    {int(c['volume']):,} (20d avg {int(c['avg20']):,}, ratio {c['ratio']:.1f}x)\n"
    )


class Catalyst2(CatalystBase):
    name = "Neocloud Distress"

    def __init__(self, edgar: EdgarClient | None = None, state: State | None = None,
                 watchlist: dict[str, str] | None = None,
                 price_fetch=None):
        self._edgar = edgar or EdgarClient()
        self._state = state or State("c2")
        self._watchlist = watchlist if watchlist is not None else NEOCLOUDS
        self._price_fetch = price_fetch  # injectable yfinance shim

    def run(self) -> list[Alert]:
        alerts: list[Alert] = []
        for ticker, cik in self._watchlist.items():
            # Filings (10-K / 10-Q for text patterns; 8-K for item codes)
            for filing in self._edgar.recent_filings(cik, forms=("10-K", "10-Q", "8-K")):
                if self._state.seen("c2_filings", filing.accession):
                    continue
                if filing.form == "8-K":
                    distress = [it for it in filing.items if it in DISTRESS_ITEMS]
                    self._state.mark_seen("c2_filings", filing.accession)
                    if distress:
                        sev = _max_sev([DISTRESS_ITEMS[it][0] for it in distress])
                        alerts.append(Alert(
                            catalyst="C2",
                            severity=sev,
                            subject=f"[C2-{sev}] {ticker} 8-K: distress item(s) {','.join(distress)}",
                            body=_render_8k_body(ticker, filing, distress),
                        ))
                else:
                    text = self._edgar.get_filing_text(filing)
                    hits = scan_text(text)
                    self._state.mark_seen("c2_filings", filing.accession)
                    if hits:
                        sev = _max_sev([h["severity"] for h in hits])
                        alerts.append(Alert(
                            catalyst="C2",
                            severity=sev,
                            subject=f"[C2-{sev}] {ticker} {filing.form}: distress language detected",
                            body=_render_filing_body(ticker, filing, hits),
                        ))

            # Stock crash check (one per ticker per day)
            try:
                crash = stock_crash(ticker, fetch=self._price_fetch)
            except Exception as e:
                crash = None
                # Non-fatal — yfinance may rate-limit or fail; continue.
                print(f"c2: stock_crash({ticker}) failed: {e}")
            if crash:
                key = f"{ticker}|{crash['date']}"
                if not self._state.seen("c2_crash", key):
                    self._state.mark_seen("c2_crash", key)
                    alerts.append(Alert(
                        catalyst="C2",
                        severity="HIGH",
                        subject=f"[C2-HIGH] {ticker}: crash {crash['change_pct']*100:.1f}% on {crash['ratio']:.1f}x volume",
                        body=_render_crash_body(ticker, crash),
                    ))
        return alerts


def _main(argv: list[str] | None = None) -> int:
    import argparse
    from lib.notify import send_alert

    p = argparse.ArgumentParser(description="Catalyst 2: Neocloud distress")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-prices", action="store_true", help="skip yfinance crash detector")
    args = p.parse_args(argv)

    price_fetch = (lambda t: __import__("pandas").DataFrame()) if args.no_prices else None
    cat = Catalyst2(price_fetch=price_fetch)
    alerts = cat.run()
    if not alerts:
        print("c2: no alerts")
        return 0
    for a in alerts:
        if args.dry_run:
            print("=" * 72)
            print(a.subject)
            print(a.body)
        else:
            send_alert(a.subject, a.body, severity=a.severity)
    print(f"c2: {len(alerts)} alert(s) {'printed' if args.dry_run else 'emailed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

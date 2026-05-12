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


def _main(argv: list[str] | None = None) -> int:
    from catalysts.base import run_cli
    return run_cli(
        lambda args: Catalyst1(),
        description="Catalyst 1: GPU Depreciation scanner",
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(_main())

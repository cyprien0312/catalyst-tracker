"""Catalyst 3 — OpenAI Financial Stress."""
from __future__ import annotations

import re

from catalysts.base import Alert, CatalystBase
from lib.edgar import EdgarClient
from lib.rss import Entry, fetch_many
from lib.state import State

# Default feed list. Google News is the most reliable substrate.
DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?q=OpenAI+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://feeds.bloomberg.com/technology/news.rss",
    "https://feeds.content.dowjones.io/public/rss/RSSWSJD",
]

CRITICAL_TOKENS = (
    "bond", "prospectus", "default", "covenant", "write-down", "writedown",
    "impair", "impairment", "restructuring",
)
HIGH_TOKENS = (
    "burn rate", "losses", "down round", "valuation cut", "ipo",
)
MED_TOKENS = ("sarah friar", "revenue")

# Pre-filter so we only consider items that mention OpenAI / GPT / Altman.
_OPENAI_RE = re.compile(r"\b(openai|altman|chatgpt|gpt-?[0-9])\b", re.I)


def classify(text: str) -> str | None:
    """Return severity if the text mentions OpenAI AND a tier token."""
    if not _OPENAI_RE.search(text):
        return None
    low = text.lower()
    if any(tok in low for tok in CRITICAL_TOKENS):
        return "CRITICAL"
    if any(tok in low for tok in HIGH_TOKENS):
        return "HIGH"
    if any(tok in low for tok in MED_TOKENS):
        return "MED"
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


class Catalyst3(CatalystBase):
    name = "OpenAI Financial Stress"

    MSFT_CIK = "0000789019"

    def __init__(self, edgar: EdgarClient | None = None, state: State | None = None,
                 feeds: list[str] | None = None):
        self._edgar = edgar or EdgarClient()
        self._state = state or State("c3")
        self._feeds = feeds if feeds is not None else DEFAULT_FEEDS

    def run(self) -> list[Alert]:
        alerts: list[Alert] = []

        # News
        for entry in fetch_many(self._feeds, self._state):
            text = f"{entry.title}\n{entry.summary}"
            sev = classify(text)
            if not sev:
                continue
            alerts.append(Alert(
                catalyst="C3",
                severity=sev,
                subject=f"[C3-{sev}] {entry.title[:120]}",
                body=_render_news_body(entry, sev),
            ))

        # MSFT filings — scan for OpenAI mentions paired with CRITICAL tokens.
        for filing in self._edgar.recent_filings(self.MSFT_CIK, forms=("10-K", "10-Q")):
            if self._state.seen("c3_msft_filings", filing.accession):
                continue
            text = self._edgar.get_filing_text(filing)
            self._state.mark_seen("c3_msft_filings", filing.accession)
            sev = classify(text)
            if sev != "CRITICAL":
                continue
            alerts.append(Alert(
                catalyst="C3",
                severity=sev,
                subject=f"[C3-{sev}] MSFT {filing.form}: OpenAI critical-tier mention",
                body=(
                    f"Form:      {filing.form}\n"
                    f"Filed:     {filing.filed_date}\n"
                    f"Accession: {filing.accession}\n"
                    f"URL:       {filing.url}\n"
                ),
            ))
        return alerts


def _main(argv: list[str] | None = None) -> int:
    import argparse
    from lib.notify import send_alert

    p = argparse.ArgumentParser(description="Catalyst 3: OpenAI stress")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-edgar", action="store_true", help="skip MSFT filings scan")
    args = p.parse_args(argv)

    cat = Catalyst3()
    if args.no_edgar:
        # Run only the news path.
        from lib.rss import fetch_many
        entries = fetch_many(cat._feeds, cat._state)
        alerts = []
        for entry in entries:
            sev = classify(f"{entry.title}\n{entry.summary}")
            if sev:
                alerts.append(Alert(
                    catalyst="C3", severity=sev,
                    subject=f"[C3-{sev}] {entry.title[:120]}",
                    body=_render_news_body(entry, sev),
                ))
    else:
        alerts = cat.run()
    if not alerts:
        print("c3: no alerts")
        return 0
    for a in alerts:
        if args.dry_run:
            print("=" * 72)
            print(a.subject)
            print(a.body)
        else:
            send_alert(a.subject, a.body, severity=a.severity)
    print(f"c3: {len(alerts)} alert(s) {'printed' if args.dry_run else 'emailed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

"""Catalyst 3 — OpenAI Financial Stress."""
from __future__ import annotations

import re

from catalysts.base import Alert, CatalystBase
from lib.edgar import EdgarClient
from lib.explanations import append_context
from lib.rss import Entry, entry_text, fetch_many
from lib.state import State

# Default feed list. Google News is the most reliable substrate.
DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?q=OpenAI+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://feeds.bloomberg.com/technology/news.rss",
    "https://feeds.content.dowjones.io/public/rss/RSSWSJD",
]

# Proximity window: a tier token must appear within this many characters of an
# OpenAI mention to count. This kills the "MSFT 10-Q mentions OpenAI in one
# paragraph and 'impairment of goodwill' in an unrelated paragraph" FP.
PROXIMITY_WINDOW = 120

# Tokens are tier-level keywords. Each tier is a list of regex fragments —
# word-boundary anchored where possible so "ipo" doesn't match "iponomy".
CRITICAL_TOKENS = (
    r"bond\b",
    # 'default' must be a debt sense, not "default ChatGPT/mode/model" (a common
    # OpenAI-news false positive). Negative lookahead drops the adjective uses.
    r"\bdefault(?:s|ed|ing)?\b(?!\s+(?:chatgpt|gpt|mode|model|setting|option|behaviou?r|app|browser|voice|view|state|value|page|account))",
    r"\bcovenant\b", r"\bwrite[- ]?down\b",
    r"\bimpair(?:ment|ed)\b",      # requires word boundary; not just "impair" substring
    r"\brestructuring\b",
    r"\bgoing\s+concern\b",
)
# Note: bare "prospectus" was removed — in OpenAI news it is almost always an
# *IPO* prospectus (MED-tier chatter), while a genuine debt/bond prospectus is
# still caught by the "bond" token.
HIGH_TOKENS = (
    r"\bburn\s+rate\b", r"\bcash\s+burn\b",
    r"\bdown\s+round\b", r"\bvaluation\s+cut\b",
)
MED_TOKENS = (
    r"\bSarah\s+Friar\b",          # case-sensitive: proper noun
    r"\bnet\s+loss(es)?\b",        # context token — quoted in every OpenAI recap
    r"\bIPO\b",                    # context token — daily speculation; case-sensitive
)

# Sense guards for tokens whose plain form is ambiguous in headlines. Proximity
# alone cannot tell which *sense* a word carries, and CRITICAL is the only C3
# tier that emails — so a wrong sense here costs a real e-mail. Each entry is
# checked against the whole text; `require` must be present, `exclude` must not.
#
# Measured against 1595 real C3 alerts: 5 of the 9 CRITICALs were false
# positives, and these two guards account for four of them.
_TOKEN_GUARDS: dict[str, dict[str, str]] = {
    # "restructuring" in AI news is overwhelmingly *organisational*, not
    # financial. Real FPs: "Starling to cut 130 roles in AI-driven
    # restructuring", "Meta Admits AI Restructuring Fell Short", "OpenAI's Head
    # of Safety Exits Amid Restructuring".
    r"\brestructuring\b": {
        "exclude": r"\b(?:roles?|jobs?|staff|layoffs?|headcount|teams?|personnel|"
                   r"reorg\w*|exits?|departs?|head\s+of|leadership|hiring)\b",
    },
    # "default" as a debt event, not a setting. The existing negative lookahead
    # only covers `default <noun>`; it misses the sentence-final noun use, as in
    # "...should become the long-term default".
    r"\bdefault(?:s|ed|ing)?\b(?!\s+(?:chatgpt|gpt|mode|model|setting|option|behaviou?r|app|browser|voice|view|state|value|page|account))": {
        "require": r"\b(?:debt|loan|bond|note|payment|covenant|obligation|creditor|"
                   r"lender|credit\s+facility|repay\w*|interest)\b",
    },
}


def _guard_ok(text: str, pattern: str) -> bool:
    g = _TOKEN_GUARDS.get(pattern)
    if not g:
        return True
    if "require" in g and not re.search(g["require"], text, re.I):
        return False
    if "exclude" in g and re.search(g["exclude"], text, re.I):
        return False
    return True

# Feeds we treat as primary sources. HIGH-tier hits from non-primary feeds
# (Google News opinion columns, aggregators) get downgraded to MED — the
# keyword is present but a single secondary headline isn't a stress signal.
PRIMARY_SOURCE_DOMAINS = (
    "bloomberg.com",
    "dowjones.io",      # WSJ feeds
    "wsj.com",
    "reuters.com",
    "ft.com",
)


def _is_primary_source(feed_url: str) -> bool:
    return any(d in feed_url for d in PRIMARY_SOURCE_DOMAINS)

# OpenAI / Altman / ChatGPT / GPT-N references.
_OPENAI_RE = re.compile(r"\b(openai|altman|chatgpt|gpt-?[0-9])\b", re.I)


def _near_openai(text: str, token_pattern: str, *, case_sensitive: bool) -> bool:
    """True if any match of token_pattern is within PROXIMITY_WINDOW chars
    of an OpenAI mention."""
    flags = 0 if case_sensitive else re.I
    openai_spans = [m.span() for m in _OPENAI_RE.finditer(text)]
    if not openai_spans:
        return False
    for tm in re.finditer(token_pattern, text, flags=flags):
        ts, te = tm.span()
        for os_, oe in openai_spans:
            # Distance from nearest edge to nearest edge.
            if ts >= oe:
                gap = ts - oe
            elif os_ >= te:
                gap = os_ - te
            else:
                gap = 0  # overlapping
            if gap <= PROXIMITY_WINDOW:
                return True
    return False


def classify(text: str) -> str | None:
    """Return severity tier if the text contains an OpenAI mention with a
    tier token within PROXIMITY_WINDOW characters. Severity falls through
    CRITICAL → HIGH → MED."""
    if not _OPENAI_RE.search(text):
        return None
    # IPO and proper nouns are case-sensitive; the rest case-insensitive.
    for pat in CRITICAL_TOKENS:
        if _near_openai(text, pat, case_sensitive=False) and _guard_ok(text, pat):
            return "CRITICAL"
    for pat in HIGH_TOKENS:
        if _near_openai(text, pat, case_sensitive=False) and _guard_ok(text, pat):
            return "HIGH"
    for pat in MED_TOKENS:
        cs = pat in (r"\bSarah\s+Friar\b", r"\bIPO\b")
        if _near_openai(text, pat, case_sensitive=cs) and _guard_ok(text, pat):
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
            text = entry_text(entry)
            sev = classify(text)
            if not sev:
                continue
            if sev == "HIGH" and not _is_primary_source(entry.feed_url):
                sev = "MED"
            body = append_context(
                _render_news_body(entry, sev), "C3", sev,
                snippet=text[:4000],
            )
            alerts.append(Alert(
                catalyst="C3",
                severity=sev,
                subject=f"[C3-{sev}] {entry.title[:120]}",
                body=body,
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
            body = append_context(
                (
                    f"Form:      {filing.form}\n"
                    f"Filed:     {filing.filed_date}\n"
                    f"Accession: {filing.accession}\n"
                    f"URL:       {filing.url}\n"
                ),
                "C3", sev,
                ticker="MSFT",
                snippet=text[:4000],
            )
            alerts.append(Alert(
                catalyst="C3",
                severity=sev,
                subject=f"[C3-{sev}] MSFT {filing.form}: OpenAI critical-tier mention",
                body=body,
            ))
        return alerts


class _Catalyst3NewsOnly(Catalyst3):
    """News-only variant used by `--no-edgar`."""
    def run(self) -> list[Alert]:
        from lib.rss import entry_text, fetch_many
        alerts: list[Alert] = []
        for entry in fetch_many(self._feeds, self._state):
            text = entry_text(entry)
            sev = classify(text)
            if sev:
                if sev == "HIGH" and not _is_primary_source(entry.feed_url):
                    sev = "MED"
                body = append_context(
                    _render_news_body(entry, sev), "C3", sev,
                    snippet=text[:4000],
                )
                alerts.append(Alert(
                    catalyst="C3", severity=sev,
                    subject=f"[C3-{sev}] {entry.title[:120]}",
                    body=body,
                ))
        return alerts


def _main(argv: list[str] | None = None) -> int:
    from catalysts.base import run_cli

    def _factory(args):
        return _Catalyst3NewsOnly() if args.no_edgar else Catalyst3()

    def _extra(p):
        p.add_argument("--no-edgar", action="store_true", help="skip MSFT filings scan")

    return run_cli(_factory, description="Catalyst 3: OpenAI stress",
                   extra_args=_extra, argv=argv)


if __name__ == "__main__":
    raise SystemExit(_main())

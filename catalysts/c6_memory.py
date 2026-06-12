"""Catalyst 6 — Memory/Storage price stress.

Tracks DRAM/NAND/HBM/SSD/HDD price-cycle news. The thesis: memory and
storage prices are the *upstream* thermometer of the AI-capex buildout —
contract-price rollover and order cancellations historically lead
hyperscaler capex cuts by one to two quarters. This catalyst watches for
the turn, not the boom:

- CRITICAL — order cancellations / inventory write-downs / capex cuts
  tied to memory makers: the unwind has reached real money.
- HIGH     — price reversal language (cuts, declines, oversupply, glut,
  inventory correction): the leading indicator itself.
- MED      — blow-off-top froth (price surges, shortages, allocation,
  record highs): confirms the cycle is late, not yet turning.

Source substrate is Google News RSS (same approach as C3) — TrendForce,
DigiTimes and the financial press all flow through it.
"""
from __future__ import annotations

import re

from catalysts.base import Alert, CatalystBase
from lib.explanations import append_context
from lib.rss import Entry, fetch_many
from lib.state import State

DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?q=%22DRAM%22+price+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=%22NAND%22+price+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=%22HBM%22+OR+%22memory+chip%22+price+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=%22SSD%22+OR+%22HDD%22+OR+%22hard+drive%22+price+when:1d&hl=en-US&gl=US&ceid=US:en",
]

# A tier token must appear within this many characters of a memory-subject
# mention to count (same FP guard as C3's OpenAI proximity window).
PROXIMITY_WINDOW = 120

# Memory/storage subject — product terms, not company names (company names
# alone produce earnings-season noise).
_SUBJECT_RE = re.compile(
    r"\b(dram|nand|hbm[0-9e]*|ddr[3-5]|flash\s+memory|memory\s+chips?|"
    r"memory\s+prices?|ssd|hdd|hard\s+(?:disk|drive)s?|enterprise\s+storage)\b",
    re.I,
)

# Consumer-deal noise guard: "SSD prices drop for Prime Day" is retail,
# not cycle signal. Any of these kills the entry outright.
_DEAL_NOISE_RE = re.compile(
    r"\b(black\s+friday|cyber\s+monday|prime\s+day|deal[s]?\b|discount|"
    r"coupon|best\s+buy|amazon\s+sale|lowest\s+price\s+ever)\b",
    re.I,
)

# The unwind reached real money.
CRITICAL_TOKENS = (
    r"\border\s+cancellations?\b",
    r"\bcancel(?:s|led|ed|ling)?\s+(?:\w+\s+){0,2}orders?\b",
    r"\binventory\s+write[- ]?downs?\b",
    r"\bcapex\s+cuts?\b",
    r"\bcapacity\s+cuts?\b",
)

# Price reversal — the leading indicator this catalyst exists for.
HIGH_TOKENS = (
    r"\bprice[s]?\s+(?:cut|cuts|decline|declining|fall|falling|fell|drop|"
    r"dropping|dropped|slid|slide|slump|plunge|plunged|tumble|tumbled)\b",
    r"\b(?:cut(?:s|ting)?|lower(?:s|ed|ing)?)\s+(?:\w+\s+){0,2}prices?\b",
    r"\boversupply\b",
    r"\bglut\b",
    r"\binventory\s+(?:correction|adjustment|glut)\b",
    r"\border\s+cuts?\b",
    r"\bdemand\s+(?:weakness|slowdown|slump)\b",
    r"\butilization\s+cuts?\b",
)

# Blow-off-top froth — confirms late cycle, not yet a turn.
MED_TOKENS = (
    r"\bprice[s]?\s+(?:hike|hikes|increase|increases|surge|surged|surging|"
    r"jump|jumped|spike|spiked|soar|soared|rally|rallied)\b",
    r"\b(?:raise|hike)[sd]?\s+(?:\w+\s+){0,2}prices?\b",
    r"\brecord\s+high\b",
    r"\bshortage[s]?\b",
    r"\bsold\s+out\b",
    r"\bon\s+allocation\b",
    r"\bsupply\s+(?:crunch|squeeze|tight(?:ness)?)\b",
    r"\bdouble[- ]book(?:ing|ed)?\b",
)

_TIERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("CRITICAL", "C6_ORDER_UNWIND", CRITICAL_TOKENS),
    ("HIGH", "C6_PRICE_REVERSAL", HIGH_TOKENS),
    ("MED", "C6_PRICE_SURGE", MED_TOKENS),
)


def _near_subject(text: str, token_pattern: str) -> bool:
    """True if any token match is within PROXIMITY_WINDOW chars of a
    memory-subject mention."""
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
    """Return (severity, signal_kind) if the text pairs a memory-subject
    mention with a tier token nearby. CRITICAL → HIGH → MED fall-through.
    Consumer-deal noise is rejected outright."""
    if not _SUBJECT_RE.search(text):
        return None
    if _DEAL_NOISE_RE.search(text):
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


class Catalyst6(CatalystBase):
    name = "Memory/Storage Price Stress"

    def __init__(self, state: State | None = None,
                 feeds: list[str] | None = None):
        self._state = state or State("c6")
        self._feeds = feeds if feeds is not None else DEFAULT_FEEDS

    def run(self) -> list[Alert]:
        alerts: list[Alert] = []
        for entry in fetch_many(self._feeds, self._state):
            text = f"{entry.title}\n{entry.summary}"
            hit = classify(text)
            if not hit:
                continue
            sev, kind = hit
            body = append_context(
                _render_news_body(entry, sev), "C6", kind,
                snippet=text[:4000],
            )
            alerts.append(Alert(
                catalyst="C6",
                severity=sev,
                subject=f"[C6-{sev}] {entry.title[:120]}",
                body=body,
            ))
        return alerts


def _main(argv: list[str] | None = None) -> int:
    from catalysts.base import run_cli

    def _factory(args):
        return Catalyst6()

    return run_cli(_factory, description="Catalyst 6: Memory/storage price stress",
                   argv=argv)


if __name__ == "__main__":
    raise SystemExit(_main())

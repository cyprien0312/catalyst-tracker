"""Sentence-level context gating for the C1/C2 filing-text scanners.

The C1/C2 regexes match *words*, not *disclosures*. Every 10-K and 10-Q carries
accounting-policy boilerplate and risk-factor hypotheticals built from exactly
the vocabulary of the real event, so a bare keyword hit is no evidence that
anything happened. Two live false positives this module exists to kill:

  * AMZN "Use of Estimates" note — "Estimates are used for, but not limited to,
    ... impairment of property and equipment and operating leases, income taxes,
    ..." Present verbatim in every AMZN 10-Q; fired C1-HIGH on 2026-07-31.
  * APLD FY2026 10-K risk factors — "any adverse developments affecting
    [subsidiary], including ... debt covenant defaults or other liabilities,
    could have a material adverse effect ..." Fired C2-HIGH on 2026-07-30 and
    flipped the buy-plan regime A -> B.

Scope is the *sentence*, deliberately, and not a character window: in AMZN's
FY2025 10-K the genuine useful-life change ("we changed our estimate of the
useful lives of a subset of our servers and networking equipment from six years
to five years") sits roughly 150 characters after the "but not limited to"
list, so any window wide enough to see the boilerplate also swallows the real
signal.

The gate **fails open**: a sentence matching none of the markers is treated as a
disclosure. Suppressing a real signal is the expensive mistake here because it
is silent, so only sentences that positively look like policy boilerplate or
pure forward-looking risk language are dropped.

`lib.edgar._strip_html` collapses all whitespace, so filing text arrives as one
long line — sentence splitting is on punctuation alone, with an abbreviation
guard so "U.S." / "Inc." / "$ 119.3 million" do not split.
"""
from __future__ import annotations

import re

# Hard cap on how far either side of a match we look for a sentence boundary.
# Filing tables can run for thousands of characters without punctuation; without
# a cap a single table would be treated as one enormous "sentence" and drag in
# unrelated boilerplate.
MAX_SENTENCE_SPAN = 600

# Trailing abbreviations whose period does not end a sentence.
_ABBREV_TAIL = re.compile(
    r"(?:^|\s)(?:Inc|Corp|Co|Ltd|LLC|LP|Nos?|Note|Item|Mr|Mrs|Ms|Dr|Jr|Sr|St|Fig"
    r"|approx|etc|vs|al|e\.g|i\.e|U\.S|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.$",
    re.I,
)

# Accounting-policy prose: enumerations of what management's estimates cover,
# and the ASC 360 "we review long-lived assets for impairment" policy note.
# Both name the event without reporting one.
BOILERPLATE = re.compile(
    r"but\s+not\s+limited\s+to"
    r"|estimates?\s+(?:and\s+assumptions\s+)?are\s+used\s+for"
    r"|use\s+of\s+estimates"
    r"|critical\s+accounting"
    r"|significant\s+accounting\s+polic"
    r"|when\s+events\s+or\s+changes\s+in\s+circumstances"
    r"|may\s+not\s+be\s+recoverable",
    re.I,
)

# Forward-looking / conditional framing — the risk-factor voice.
HYPOTHETICAL = re.compile(
    r"\b(?:could|would|may|might)\b"
    r"|\bif\s+(?:we|our|the\s+company)\b"
    r"|\bno\s+assurance\b"
    r"|\brisks?\s+that\b",
    re.I,
)

# Assertions that something actually happened, including a quantified amount.
# Beats HYPOTHETICAL when both are present, so a real disclosure that also
# describes its consequences ("we recorded a $500M impairment, which may grow")
# still alerts.
AFFIRMATIVE = re.compile(
    r"\brecord(?:ed|s)\b|\brecogniz(?:ed|es)\b|\bincurred\b"
    r"|\bwrote\s+down\b|\bwrite-?downs?\b|\bresulted\s+in\b"
    r"|\braised\s+substantial\s+doubt\b|\bdeclared\b|\bdefaulted\b|\bbreached\b"
    r"|\b(?:was|were)\s+required\b|\b(?:was|were)\s+not\s+in\s+compliance\b"
    r"|\bfailed\s+to\s+comply\b|\bobtained\b|\breceived\s+(?:a\s+)?notice\b"
    r"|\bentered\s+into\b|\bhas\s+occurred\b|\bwe\s+(?:changed|completed)\b"
    r"|\$\s?\d[\d,]*(?:\.\d+)?",
    re.I,
)


def _is_boundary(text: str, idx: int) -> bool:
    """True if ``text[idx]`` terminates a sentence."""
    if text[idx] not in ".!?":
        return False
    # A period not followed by whitespace is a decimal point or an initial.
    if idx + 1 < len(text) and not text[idx + 1].isspace():
        return False
    return not _ABBREV_TAIL.search(text[max(0, idx - 12): idx + 1])


def sentence_at(text: str, start: int, end: int) -> str:
    """Return the sentence containing ``text[start:end]``.

    Falls back to a ``MAX_SENTENCE_SPAN`` window on either side when no boundary
    is found (tables, headings, and other punctuation-free runs).
    """
    floor = max(0, start - MAX_SENTENCE_SPAN)
    lo = floor
    for i in range(start - 1, floor - 1, -1):
        if _is_boundary(text, i):
            lo = i + 1
            break

    ceiling = min(len(text), end + MAX_SENTENCE_SPAN)
    hi = ceiling
    for i in range(end, ceiling):
        if _is_boundary(text, i):
            hi = i + 1
            break

    return text[lo:hi].strip()


def is_disclosure(sentence: str) -> bool:
    """True if ``sentence`` reports an event rather than describing a policy or a risk."""
    if BOILERPLATE.search(sentence):
        return False
    if AFFIRMATIVE.search(sentence):
        return True
    return not HYPOTHETICAL.search(sentence)


def find_disclosure(
    text: str,
    rx: re.Pattern[str],
    requires: re.Pattern[str] | None = None,
) -> tuple[re.Match[str], str] | None:
    """First match of ``rx`` in ``text`` that survives the context gate.

    Scanning every occurrence rather than only the first matters: boilerplate
    reliably appears in the accounting-policy note near the top of a filing,
    ahead of any real disclosure in the notes or MD&A. ``re.search`` would let
    that boilerplate mask a genuine signal further down.

    ``requires`` is an optional per-pattern subject check applied to the same
    sentence — used where the bare pattern is too generic to identify what it is
    talking about (e.g. "5.5 years" also matches a contract-duration sentence).
    """
    for m in rx.finditer(text):
        sentence = sentence_at(text, m.start(), m.end())
        if not is_disclosure(sentence):
            continue
        if requires is not None and not requires.search(sentence):
            continue
        return m, sentence
    return None


def scan(
    text: str,
    compiled: list[tuple[str, re.Pattern[str], str]],
    requires: dict[str, re.Pattern[str]] | None = None,
) -> list[dict]:
    """Run gated pattern scan, returning at most one hit per pattern key.

    Each hit carries the matched text (``snippet``) and the sentence it came
    from (``sentence``) so an alert body shows enough context for a reader to
    judge the hit without opening the filing.
    """
    requires = requires or {}
    out: list[dict] = []
    for key, rx, sev in compiled:
        found = find_disclosure(text, rx, requires.get(key))
        if found is None:
            continue
        m, sentence = found
        out.append({
            "key": key,
            "severity": sev,
            "snippet": m.group(0)[:240],
            "sentence": sentence[:600],
        })
    return out

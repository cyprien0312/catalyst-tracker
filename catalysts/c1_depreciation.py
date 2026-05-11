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

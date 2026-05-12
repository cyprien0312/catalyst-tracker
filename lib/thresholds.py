"""Central registry of all catalyst trigger thresholds.

Importing from here ensures the dashboard and the catalysts read the same
numbers. Tune a threshold by editing this file, pushing, and the next cron
tick picks it up.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Threshold:
    catalyst: str
    name: str
    value: str          # rendered as text in dashboard
    severity: str       # tier when fired
    note: str = ""


# C1 — text regex catalyst. No numeric thresholds; severity assigned per pattern.
C1_THRESHOLDS = [
    Threshold("C1", "Useful life shortened 6→5 years",   "regex hit",       "HIGH",
              "Amazon FY2024 10-K verbatim trigger"),
    Threshold("C1", "Useful life study language",        "regex hit",       "HIGH",
              "Anchored on AMZN/META 10-K phrasing"),
    Threshold("C1", "META 5.5-year language",            "regex hit",       "MED",
              "Generic; alone is not enough to act on"),
    Threshold("C1", "Accelerated depreciation + server", "regex hit",       "HIGH",
              "Impairment proxy"),
    Threshold("C1", "Estimate change near equipment",    "regex hit",       "HIGH"),
]

# C2 — neocloud distress.
C2_THRESHOLDS = [
    Threshold("C2", "Going-concern language",   "regex hit",  "CRITICAL",
              "10-K/10-Q text"),
    Threshold("C2", "Covenant distress",        "regex hit",  "HIGH",
              "breach|default|waiver|amendment"),
    Threshold("C2", "Material adverse change",  "regex hit",  "HIGH",
              "near liquidity/debt"),
    Threshold("C2", "8-K item 2.04 / 4.02 / 1.03", "filing", "CRITICAL",
              "debt acceleration / non-reliance / bankruptcy"),
    Threshold("C2", "Stock crash price drop",   "≤ −15%",     "HIGH",
              "Single-session close"),
    Threshold("C2", "Stock crash volume ratio", "≥ 3.0× 20d avg", "HIGH",
              "Both price AND volume must hit"),
]

# C3 — OpenAI stress.
from catalysts import c3_openai  # noqa: E402 — break circular by lazy use below
_C3_WIN = c3_openai.PROXIMITY_WINDOW
C3_THRESHOLDS = [
    Threshold("C3", "OpenAI proximity window",  f"≤ {_C3_WIN} chars", "—",
              "Tier token must be within this many chars of an OpenAI mention"),
    Threshold("C3", "CRITICAL tier tokens",     ", ".join(c3_openai.CRITICAL_TOKENS),
              "CRITICAL"),
    Threshold("C3", "HIGH tier tokens",         ", ".join(c3_openai.HIGH_TOKENS),
              "HIGH"),
    Threshold("C3", "MED tier tokens",          ", ".join(c3_openai.MED_TOKENS),
              "MED",
              "Case-sensitive proper nouns only"),
]

# C4 — capex / cash-flow.
from catalysts import c4_capex  # noqa: E402
C4_THRESHOLDS = [
    Threshold("C4", "TTM Capex/OCF cross",      f"≥ {c4_capex.RATIO_CROSS_THRESHOLD*100:.0f}%",
              "HIGH",
              "Upward cross of the prior quarter's value"),
    Threshold("C4", "QoQ ratio jump",           f"≥ {c4_capex.RATIO_JUMP_PP*100:.0f} pp",
              "MED"),
    Threshold("C4", "TTM Free Cash Flow",       "< 0",  "HIGH",
              "OCF − Capex over trailing four quarters"),
]

# C5 — grid bottlenecks.
from catalysts import c5_grid  # noqa: E402
C5_THRESHOLDS = [
    Threshold("C5", "Henry Hub 12-mo strip avg", f"≥ ${c5_grid.HENRY_HUB_STRESS:.2f}/MMBtu",
              "MED",
              "Average of front-month + 11 futures contracts"),
    Threshold("C5", "MoM queue MW drop",        f"≥ {c5_grid.MOM_DROP_PCT:.0f}%",
              "MED"),
    Threshold("C5", "Weekly new withdrawals",   f"≥ {c5_grid.WITHDRAWN_THRESHOLD}",
              "HIGH",
              "Projects ≥ 100 MW"),
]


def all_thresholds() -> list[Threshold]:
    return [
        *C1_THRESHOLDS, *C2_THRESHOLDS, *C3_THRESHOLDS,
        *C4_THRESHOLDS, *C5_THRESHOLDS,
    ]

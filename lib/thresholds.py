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


# C6 — memory/storage price stress.
from catalysts import c6_memory  # noqa: E402
_C6_WIN = c6_memory.PROXIMITY_WINDOW
C6_THRESHOLDS = [
    Threshold("C6", "Subject proximity window",  f"≤ {_C6_WIN} chars", "—",
              "Tier token must be near a DRAM/NAND/HBM/SSD/HDD mention"),
    Threshold("C6", "Order unwind tokens",       "cancel orders, inventory write-down, capex cut",
              "CRITICAL",
              "The downturn reaching real money"),
    Threshold("C6", "Price reversal tokens",     "price cut/fall/drop, oversupply, glut, inventory correction",
              "HIGH",
              "Leading indicator — memory tops lead capex cuts by 1-2 quarters"),
    Threshold("C6", "Price surge tokens",        "price hike/surge, shortage, allocation, record high",
              "MED",
              "Blow-off-top confirmation; consumer-deal headlines filtered out"),
]


# C7 — credit market stress.
from catalysts import c7_credit  # noqa: E402
C7_THRESHOLDS = [
    Threshold("C7", "HY OAS widening off 90d low",
              f"≥ +{c7_credit.SERIES['HY']['widen_trigger']*100:.0f} bp", "MED",
              "HIGH at 2×; the fuse lighting"),
    Threshold("C7", "HY OAS absolute stress",
              f"≥ {c7_credit.SERIES['HY']['stress_level']*100:.0f} bp", "HIGH"),
    Threshold("C7", "IG OAS widening off 90d low",
              f"≥ +{c7_credit.SERIES['IG']['widen_trigger']*100:.0f} bp", "MED",
              "HIGH at 2×"),
    Threshold("C7", "IG OAS absolute stress",
              f"≥ {c7_credit.SERIES['IG']['stress_level']*100:.0f} bp", "HIGH"),
]

# C8 — macro triggers.
from catalysts import c8_macro  # noqa: E402
C8_THRESHOLDS = [
    Threshold("C8", "CPI YoY hot", f"≥ {c8_macro.CPI_HOT_THRESHOLD:.1f}%", "MED",
              f"HIGH at ≥ {c8_macro.CPI_HOT_HIGH:.1f}%"),
    Threshold("C8", "CPI YoY re-acceleration",
              f"2 mo rising, ≥ {c8_macro.CPI_REACCEL_FLOOR:.1f}%", "MED",
              "Direction over level"),
    Threshold("C8", "Core PCE YoY hot", f"≥ {c8_macro.PCE_HOT_THRESHOLD:.1f}%", "MED",
              f"HIGH at ≥ {c8_macro.PCE_HOT_HIGH:.1f}%; the Fed's target metric"),
    Threshold("C8", "Core PCE YoY re-acceleration",
              f"2 mo rising, ≥ {c8_macro.PCE_REACCEL_FLOOR:.1f}%", "MED",
              "Direction over level"),
]

# C9 — crypto cycle top.
from catalysts import c9_crypto  # noqa: E402
C9_THRESHOLDS = [
    Threshold("C9", "BTC Mayer Multiple", f"≥ {c9_crypto.MAYER_HOT:.1f}", "MED",
              f"HIGH at ≥ {c9_crypto.MAYER_HIGH:.1f}; price/200DMA"),
    Threshold("C9", "BTC Pi Cycle Top", "111DMA crosses > 2×350DMA", "HIGH",
              "Calls cycle tops to within days"),
]

# C10 — liquidity tightening (USD / real yields).
from catalysts import c10_liquidity  # noqa: E402
C10_THRESHOLDS = [
    Threshold("C10", "Broad USD surge",
              f"≥ +{c10_liquidity.SERIES['USD']['rise_trigger']:.1f}% off 90d-low", "MED",
              "HIGH at 2×; global liquidity drain"),
    Threshold("C10", "10y real-yield spike",
              f"≥ +{c10_liquidity.SERIES['REAL10']['rise_trigger']*100:.0f} bp off 90d-low", "MED",
              "HIGH at 2×; discount-rate shock"),
    Threshold("C10", "10y real-yield restrictive",
              f"≥ {c10_liquidity.SERIES['REAL10']['stress_level']:.2f}%", "HIGH",
              "Absolute restrictive level"),
]

# C11 — SpaceX IPO unlock / passive flows.
from catalysts import c11_spacex  # noqa: E402
C11_THRESHOLDS = [
    Threshold("C11", "Unlock tranche lead time",
              f"≤ {c11_spacex.LEAD_DAYS} days out", "MED",
              "HIGH ≥8亿, CRITICAL ≥30亿 single-tranche release; "
              "earnings-linked dates are estimates"),
    Threshold("C11", "Insider-supply news tokens",
              "secondary offering / insider dump / Musk sells / lock-up waived",
              "CRITICAL", f"within {c11_spacex.PROXIMITY_WINDOW} chars of a SpaceX mention"),
    Threshold("C11", "Unlock news tokens",
              "lock-up expiry / unlock / share sale / dilution / float expansion",
              "HIGH"),
    Threshold("C11", "Index/passive-flow news tokens",
              "Nasdaq-100 / index inclusion / passive buying / price target",
              "MED"),
    Threshold("C11", "ETF position swing",
              f"|Δshares| ≥ {c11_spacex.ETF_SWING_PCT:.0f}% day-over-day", "MED",
              "HIGH on cuts and on position exits; MED on adds"),
]


def all_thresholds() -> list[Threshold]:
    return [
        *C1_THRESHOLDS, *C2_THRESHOLDS, *C3_THRESHOLDS,
        *C4_THRESHOLDS, *C5_THRESHOLDS, *C6_THRESHOLDS,
        *C7_THRESHOLDS, *C8_THRESHOLDS, *C9_THRESHOLDS,
        *C10_THRESHOLDS, *C11_THRESHOLDS,
    ]

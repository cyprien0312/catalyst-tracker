"""Human-readable explanation + implication blurbs for each catalyst signal.

Every alert subject ends up keyed by a (catalyst, signal_kind) tuple. The
`explain()` function returns a short two-paragraph note we append to the
email body so the recipient can act on it without re-reading the source spec.

Keep tone direct and avoid hedging language. Speak to *why* this is on a
"bubble-stress" tracker, not generic finance commentary.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Explanation:
    what: str                  # 1–2 sentences (English): what literally happened
    why: str                   # 1–3 sentences (English): implication for the AI-infra thesis
    what_zh: str | None = None # Chinese version — populated only by LLM path
    why_zh: str | None = None  # Chinese version — populated only by LLM path


# ---------- C1 — Depreciation useful-life ----------
_C1 = {
    "USEFUL_LIFE_SHORTENED_6_TO_5": Explanation(
        what="A hyperscaler told the SEC it is shortening the useful life of its "
             "servers and networking equipment from six years to five.",
        why="Hyperscalers extended useful lives in 2022-2023 to flatter reported earnings. "
            "Shortening them again reverses that tailwind: depreciation expense rises, "
            "operating income drops, and the implicit message is that hardware (GPUs especially) "
            "is being retired faster than planned — likely because next-gen silicon outperforms "
            "current-gen by enough that running old chips is uneconomic. Bearish for the "
            "AI-capex-payback narrative.",
    ),
    "USEFUL_LIFE_EXTENDED_4_TO_6": Explanation(
        what="A filer is extending the useful life of servers/network equipment from four to six years.",
        why="Historically Microsoft used this lever to boost earnings during the 2022 cloud slowdown. "
            "Today the trend is the opposite (shortening), so an extension would be unusual and worth "
            "investigating — either a new entrant, or accounting that's papering over weak fundamentals.",
    ),
    "USEFUL_LIFE_STUDY": Explanation(
        what="The filing mentions a 'useful life study' — the SEC term for a formal accounting reassessment of "
             "asset lifetimes.",
        why="When hyperscalers do these studies, the result is almost always an estimate change "
            "(extension or shortening) that lands as a multi-billion-dollar swing in reported "
            "earnings. The mere mention is a flag to read the filing for the resulting estimate change.",
    ),
    "AMZN_SUBSET_PHRASE": Explanation(
        what="The filing uses Amazon's verbatim 2024 10-K wording: "
             "'a subset of our servers and networking equipment'.",
        why="This phrasing was the leading edge of Amazon's $0.7B operating-income hit announced in "
            "early 2025. The presence of this exact phrase in *another* filer's 10-K signals they're "
            "copying Amazon's playbook — i.e., they too are recognizing AI hardware churn.",
    ),
    "ESTIMATE_CHANGE": Explanation(
        what="The filing discloses a 'change in accounting estimate' connected to servers, networking, "
             "or equipment.",
        why="GAAP requires these be disclosed in the period of change. They almost always have a "
            "material P&L impact (positive or negative). Read the filing to learn the direction and size.",
    ),
    "META_5_5_YEARS": Explanation(
        what="The filing mentions a 5.5-year useful life — Meta's 2024 chosen middle ground when extending.",
        why="On its own this is weak signal — '5.5 years' shows up in lots of contexts. But when combined "
            "with hyperscaler context it indicates someone is mirroring Meta's accounting choice.",
    ),
    "ACCEL_DEPREC": Explanation(
        what="The filing discloses accelerated depreciation charges on servers, GPUs, or network gear.",
        why="Accelerated depreciation is the polite term for 'this hardware is dead but we're not "
            "writing it off yet.' Amazon recorded $920M of this in Q4 2024. Each instance is a "
            "real-money admission that prior capex didn't pay back as expected.",
    ),
    "IMPAIRMENT_PPE": Explanation(
        what="The filing discloses an impairment charge against property, plant, and equipment.",
        why="Impairment is a non-cash write-down — the asset's future cash-generating ability is "
            "now believed to be less than its book value. For an AI-capex-heavy filer, this is the "
            "single hardest data point to argue away.",
    ),
}

# ---------- C2 — Neocloud distress ----------
_C2 = {
    "GOING_CONCERN": Explanation(
        what="The filing contains the SEC-mandated 'substantial doubt about ability to continue "
             "as a going concern' disclosure.",
        why="This is the single most serious financial-distress flag in US GAAP. Auditors include it "
            "when management can't credibly cover the next 12 months of obligations. Neocloud "
            "going-concern flags are existential — these are debt-funded GPU operators with "
            "single-customer concentration risk.",
    ),
    "COVENANT_DISTRESS": Explanation(
        what="The filing mentions a covenant breach, default, waiver, or amendment.",
        why="Debt covenants are tripped before bankruptcy by quarters or years. A waiver means lenders "
            "agreed to look past a breach this time. Repeated waivers signal lenders are losing "
            "patience. Bond prices and equity volatility usually move days before the filing.",
    ),
    "MATERIAL_ADVERSE": Explanation(
        what="The filing references a 'material adverse change' near liquidity or debt language.",
        why="MAC clauses let counterparties walk away from deals. Mention in a 10-Q usually means "
            "either a contract dispute or a renegotiation in progress — both are leading indicators "
            "of revenue or financing surprises.",
    ),
    "C2_ITEM_2.04": Explanation(
        what="An 8-K item 2.04 was filed: a 'Triggering Event That Accelerates a Direct Financial Obligation'.",
        why="This means debt that was supposed to mature later is now due immediately, usually because "
            "a covenant tripped. Item 2.04 filings are filed within 4 business days and routinely "
            "precede restructurings.",
    ),
    "C2_ITEM_4.02": Explanation(
        what="An 8-K item 4.02 was filed: 'Non-Reliance on Previously Issued Financial Statements'.",
        why="Management is telling the market not to trust prior financials — usually because of "
            "an accounting error or fraud finding. Among the most severe 8-K items; equity often "
            "drops 20-50% on filing.",
    ),
    "C2_ITEM_1.03": Explanation(
        what="An 8-K item 1.03 was filed: 'Bankruptcy or Receivership'.",
        why="The company has filed for bankruptcy protection or is in receivership. Equity is "
            "typically wiped out or trades near zero post-filing.",
    ),
    "C2_STOCK_CRASH": Explanation(
        what="A neocloud equity dropped ≥15% in a single session on ≥3× its 20-day average volume.",
        why="The combination of size and volume rules out routine noise. For thinly-held neoclouds, "
            "this usually corresponds to a news event (downgrade, lockup expiration, contract loss) "
            "that hits before the SEC paper trail catches up. Worth a same-day investigation.",
    ),
}

# ---------- C3 — OpenAI stress ----------
_C3 = {
    "CRITICAL": Explanation(
        what="A news item or MSFT filing mentions OpenAI near a CRITICAL-tier financial keyword "
             "(bond, prospectus, default, covenant, write-down, impair, restructuring, going-concern).",
        why="OpenAI is the linchpin AI customer for MSFT, the largest single tenant for many neoclouds, "
            "and a marquee buyer of NVDA chips. Any genuine financial-distress signal at OpenAI would "
            "cascade through every layer of the AI-infrastructure stack — read the linked source "
            "immediately.",
    ),
    "HIGH": Explanation(
        what="A news item mentions OpenAI near a HIGH-tier keyword (burn rate, losses, down round, "
             "valuation cut, IPO).",
        why="OpenAI's 2025 burn was ~$9B against $13B revenue; 2026 projected burn is ~$17B. Any "
            "of these keywords near OpenAI signals either a fresh capital raise (often at lower "
            "valuations) or a public admission of cost pressure.",
    ),
    "MED": Explanation(
        what="A news item mentions OpenAI alongside CFO Sarah Friar or generic revenue language.",
        why="Lower-confidence signal — could be routine commentary. But Sarah Friar speaking publicly "
            "often precedes financial-disclosure moments (capital raises, IR updates).",
    ),
}

# ---------- C4 — Hyperscaler capex ----------
_C4 = {
    "FCF_NEGATIVE": Explanation(
        what="A hyperscaler's trailing-twelve-month free cash flow turned from non-negative to negative.",
        why="Hyperscalers historically generated massive FCF — that's how the AI capex was supposed "
            "to be paid for. When TTM FCF goes negative, the implicit funding source switches to "
            "debt or balance sheet drawdown. Bank of America projected hyperscalers would spend "
            "~94% of operating cash flow on capex in 2026. Crossing zero on FCF means capex now "
            "exceeds *all* operating cash — they're pre-funding via debt.",
    ),
    "RATIO_CROSS": Explanation(
        what="A hyperscaler's TTM Capex/Operating-Cash-Flow ratio crossed upward through 110%.",
        why="The 10-year hyperscaler average is ~40%. UBS pegs 2026 sector ratio at 'nearly 100%'. "
            "An individual filer crossing 110% means capex now exceeds operating cash for that "
            "specific company — historically a classic late-cycle signal that the spend cycle is "
            "outrunning the revenue cycle.",
    ),
    "RATIO_JUMP": Explanation(
        what="A hyperscaler's Capex/OCF ratio jumped ≥15 percentage points quarter-over-quarter.",
        why="Even without crossing the 110% line, a 15pp jump in one quarter is unusual. Either "
            "OCF deteriorated meaningfully or capex accelerated sharply — both are worth knowing.",
    ),
}

# ---------- C5 — Grid bottlenecks ----------
_C5 = {
    "MW_DROP": Explanation(
        what="An ISO interconnection queue's total active MW dropped ≥5% since the last snapshot.",
        why="Queue shrinkage means projects are being withdrawn or suspended faster than new ones "
            "are entering. This is the early indicator of grid capacity becoming the binding "
            "constraint on AI data-center growth — slowing announced projects from hyperscalers "
            "and neoclouds alike.",
    ),
    "NEW_WITHDRAWALS": Explanation(
        what="An ISO recorded ≥5 new withdrawn/suspended projects of ≥100 MW since the prior snapshot.",
        why="Withdrawing a ≥100MW project means abandoning a years-long interconnection process. "
            "Multiple withdrawals in a single cycle is a strong indicator developers can't get the "
            "economics to work — usually because of either power-delivery delays or hyperscaler "
            "capex pullback. Watch for whether the withdrawals cluster around specific utilities.",
    ),
    "HENRY_HUB_STRESS": Explanation(
        what="The Henry Hub 12-month gas-futures strip crossed $5.00/MMBtu on average.",
        why="EIA's 2026 forecast is sub-$3.50/MMBtu. $5.00 indicates the market is pricing in "
            "structurally higher gas demand — most plausibly from data-center load growth that "
            "exceeds the gas industry's ability to bring on new supply. Higher gas prices feed into "
            "every gas-fired generator that backs up data-center load, increasing AI compute opex.",
    ),
}

# ---------- C6 — Memory/storage price stress ----------
_C6 = {
    "C6_ORDER_UNWIND": Explanation(
        what="A news item pairs a memory/storage product (DRAM, NAND, HBM, SSD, HDD) "
             "with order-cancellation, inventory-write-down, or capex-cut language.",
        why="This is the unwind reaching real money. In the 2018 and 2022 memory busts, "
            "order cancellations and inventory write-downs marked the point where the "
            "downturn became undeniable — and they preceded the broader capex contraction. "
            "For the AI thesis specifically: hyperscalers cancelling memory orders means "
            "data-center build plans are being cut, not just repriced.",
    ),
    "C6_PRICE_REVERSAL": Explanation(
        what="A news item reports memory/storage prices declining — cuts, drops, oversupply, "
             "glut, or inventory-correction language near a DRAM/NAND/HBM/SSD/HDD mention.",
        why="Memory contract prices are the most cyclical, fastest-clearing signal in the "
            "AI-hardware supply chain. A rollover after the 2025-2026 super-spike is the "
            "leading indicator this catalyst exists for: in past cycles, memory price peaks "
            "led capex cuts by one to two quarters. Watch whether reversal headlines cluster "
            "— a single soft week is noise, three consecutive weeks is a turn.",
    ),
    "C6_PRICE_SURGE": Explanation(
        what="A news item reports memory/storage prices surging — hikes, shortages, allocation, "
             "or record-high language near a DRAM/NAND/HBM/SSD/HDD mention.",
        why="Up-cycle confirmation, not a stress signal by itself. But blow-off-top behaviour "
            "(double-booking, panic allocation, 'sold out through next year') is what tops are "
            "made of — rising surge-headline frequency raises the prior that the reversal, "
            "when it comes, will be sharp. Also a direct cost headwind: every dollar of memory "
            "price increase worsens data-center capex payback math.",
    ),
}

# ---------- C7 — Credit market stress ----------
_C7 = {
    "SPREAD_WIDENING": Explanation(
        what="A corporate credit spread (high-yield or investment-grade OAS) has "
             "widened materially off its recent low.",
        why="Credit spreads are the fuse of fuses — bubbles tear open in the debt "
            "market before equities. With the AI buildout now a debt story (≈$570B "
            "of AI-linked bond issuance projected for 2026) and spreads at their "
            "tightest since 1997, the market is pricing almost no risk. The actionable "
            "signal is not the tight level but spreads STARTING to widen: that is the "
            "first sign the market is repricing AI-infra credit risk. Watch whether the "
            "widening sustains over consecutive sessions.",
    ),
    "SPREAD_STRESS": Explanation(
        what="A corporate credit spread has reached an absolute stress level "
             "(high-yield OAS ≥ 400 bp, or investment-grade OAS ≥ 125 bp).",
        why="This is no longer early-warning — credit is pricing outright distress. "
            "At these levels the refinancing window for the wall of 'B-'-and-below AI "
            "debt maturing into 2027-2028 starts to close, and GPU-collateralised "
            "loans (whose collateral depreciates faster than the borrower repays) come "
            "under pressure. A sustained move here typically precedes forced selling.",
    ),
}

# ---------- C8 — Macro triggers ----------
_C8 = {
    "CPI_HOT": Explanation(
        what="CPI year-over-year is at or above 3.5% — above the Fed's comfort zone.",
        why="The classic balloon-popping combination is inflation sticking so the Fed "
            "can't cut, squeezing high valuations and high leverage at the same time. "
            "Cheap money is the common fuel of every signal in this tracker; hot CPI "
            "means it stays expensive. Above ~4.5% the stance is clearly restrictive and "
            "rate-cut hopes priced into AI-debt issuance evaporate.",
    ),
    "CPI_REACCEL": Explanation(
        what="CPI year-over-year has risen for two consecutive months (and is above 3%).",
        why="Direction matters more than level. A re-acceleration after a disinflation "
            "trend is what forces the Fed to hold or hike — the opposite of what a "
            "debt-funded, rate-sensitive AI capex cycle needs. Two consecutive monthly "
            "increases is the earliest robust signal that disinflation has stalled.",
    ),
    "PCE_HOT": Explanation(
        what="Core PCE year-over-year is at or above 3.0% — well above the Fed's 2% target.",
        why="Core PCE is the inflation gauge the FOMC actually sets policy on, so a hot "
            "print is a more direct 'no cuts' signal than CPI. The same balloon-popping "
            "logic applies: sticky core inflation keeps money expensive and squeezes the "
            "leveraged, rate-sensitive AI-capex cycle. Above ~3.5% the stance is clearly "
            "restrictive.",
    ),
    "PCE_REACCEL": Explanation(
        what="Core PCE year-over-year has risen for two consecutive months (and is above 2.5%).",
        why="A re-acceleration in the Fed's own target metric is the cleanest signal that "
            "the disinflation that justified rate-cut expectations has stalled. It removes "
            "the FOMC's room to ease into any AI-driven credit stress — the master fuel "
            "line stays shut off.",
    ),
}

# ---------- C9 — Crypto cycle top ----------
_C9 = {
    "MAYER_HOT": Explanation(
        what="Bitcoin's Mayer Multiple (price ÷ 200-day moving average) is ≥ 2.4.",
        why="A Mayer Multiple above ~2.4 has historically marked froth zones where "
            "price is stretched far above its long-term trend. Bitcoin trades on the "
            "same risk appetite and cheap-money liquidity as the AI-equity complex, so "
            "an over-extended BTC is corroborating evidence that risk-on positioning is "
            "late-cycle. Above 2.8 the stretch is extreme.",
    ),
    "PI_CYCLE_TOP": Explanation(
        what="Bitcoin's 111-day moving average has crossed above 2× its 350-day moving "
             "average — the Pi Cycle Top trigger.",
        why="This cross has called the last several Bitcoin cycle tops to within days. "
            "It fires rarely and only near major peaks, so a trigger is a high-confidence "
            "signal that the broad risk-appetite cycle — the same one funding the AI "
            "buildout — may be topping. Treat as a cross-asset confirmation, not a "
            "standalone AI-infra signal.",
    ),
}

# ---------- C10 — Liquidity tightening (USD / real yields) ----------
_C10 = {
    "DOLLAR_SURGE": Explanation(
        what="The broad US dollar index has risen materially (≥2.5%) off its "
             "recent trailing low.",
        why="A surging dollar drains global liquidity: it tightens financial "
            "conditions worldwide without the Fed touching the policy rate, and it "
            "is the channel through which 'we might hike' jawboning actually bites. "
            "Dollar-up regimes pressure risk assets and the dollar-funded carry that "
            "leverages the AI-equity complex. Watch whether the move sustains "
            "alongside the C7 credit and C8 inflation reads.",
    ),
    "REAL_YIELD_SPIKE": Explanation(
        what="The 10-year real (inflation-adjusted) Treasury yield has risen ≥40 bp "
             "off its recent trailing low.",
        why="Real yields are the discount rate on every long-duration cash flow — "
            "and AI-infra valuations are the longest-duration bet in the market. A "
            "real-yield spike compresses those valuations directly and raises the true "
            "cost of the debt funding the buildout, regardless of where headline rates "
            "sit. This is the cleanest read on money getting genuinely more expensive.",
    ),
    "REAL_YIELD_STRESS": Explanation(
        what="The 10-year real yield is at or above an absolute restrictive level "
             "(≥2.50%).",
        why="At this level real money is outright restrictive, not merely tightening. "
            "It marks the zone where leveraged, no-current-cashflow AI bets and the "
            "refinancing of AI-linked debt come under sustained valuation pressure — "
            "the macro discount-rate equivalent of C7's outright credit stress.",
    ),
}

# ---------- C11 — SpaceX IPO unlock / passive flows ----------
_C11 = {
    "C11_UNLOCK_UPCOMING": Explanation(
        what="A SpaceX (SPCX) lock-up tranche is estimated to expire within the "
             "next week, releasing a block of insider shares into the float.",
        why="SPCX floated ~4% of its shares and was fast-tracked into the "
            "Nasdaq-100, so index funds were forced to buy into a tiny float. "
            "Each unlock expands supply against that fixed passive bid; the "
            "large tranches (Q3'26 earnings ≈13亿, Day-366 Musk tranche ≈64亿) "
            "are the live test of whether index plumbing can absorb mega-IPO "
            "distribution — the same mechanics an OpenAI/Anthropic listing "
            "would face. Earnings-linked dates are estimates; confirm on EDGAR.",
    ),
    "C11_INSIDER_SUPPLY": Explanation(
        what="News pairs SpaceX with secondary-offering / insider-dump / "
             "lock-up-waiver language: incremental supply is hitting now.",
        why="A waived or accelerated lock-up means distribution ahead of "
            "schedule — insiders prioritising exit over price. For the "
            "AI-complex thesis this is the single-name canary for how late-cycle "
            "mega-cap supply gets absorbed (or not).",
    ),
    "C11_UNLOCK_NEWS": Explanation(
        what="News pairs SpaceX with unlock / share-sale / dilution language.",
        why="Confirms the unlock calendar is becoming the market narrative. "
            "Watch whether coverage shifts from 'index inclusion demand' to "
            "'supply overhang' — that rotation historically marks the top of "
            "index-inclusion pops.",
    ),
    "C11_INDEX_FLOW": Explanation(
        what="News pairs SpaceX with index-inclusion / passive-flow / "
             "price-target language.",
        why="Passive-flow hype is the demand side of the trade. On its own it "
            "is late-cycle froth confirmation: forced buying with a known "
            "supply wave behind it is exactly the setup this tracker exists "
            "to time.",
    ),
    "C11_ETF_FLOW": Explanation(
        what="An ETF that holds SPCX changed its position materially "
             "(≥20% share-count swing, or dropped the name entirely).",
        why="Issuer holdings CSVs are a daily, free proxy for the Bloomberg "
            "ownership screen. Active cuts while lock-ups roll off signal smart "
            "money front-running the supply wave; passive adds show the index "
            "bid still absorbing. Direction matters more than size.",
    ),
}

# Composite registry: catalyst → signal_kind → Explanation
_REGISTRY: dict[str, dict[str, Explanation]] = {
    "C1": _C1,
    "C2": _C2,
    "C3": _C3,
    "C4": _C4,
    "C5": _C5,
    "C6": _C6,
    "C7": _C7,
    "C8": _C8,
    "C9": _C9,
    "C10": _C10,
    "C11": _C11,
}


_FALLBACK = Explanation(
    what="A catalyst signal fired but no detailed explanation is registered for this signal kind.",
    why="Read the alert body fields (Accession, URL, snippet) directly. See "
        "https://cyprien0312.github.io/catalyst-tracker/thresholds.html for thresholds.",
)


def explain(catalyst: str, signal_kind: str) -> Explanation:
    """Return the registered Explanation for a (catalyst, signal_kind) pair.

    Returns a graceful fallback rather than raising — explanations are advisory."""
    cat = _REGISTRY.get(catalyst.upper(), {})
    return cat.get(signal_kind, _FALLBACK)


def append_context(
    body: str,
    catalyst: str,
    signal_kind: str,
    *,
    ticker: str | None = None,
    snippet: str | None = None,
    numbers: dict | None = None,
    use_llm: bool = True,
) -> str:
    """Append a 'What this means / Why it matters' section to an alert body.

    When CATALYST_LLM_ENABLED=1 and ``use_llm`` is True, attempts an LLM-generated
    explanation tailored to the supplied ticker/snippet/numbers. Any failure
    transparently falls back to the static template registry — so existing
    callers that pass only the positional args see no behaviour change.
    """
    e: Explanation | None = None
    if use_llm:
        # Local import to avoid a hard dependency cycle (lib.llm imports from here).
        from lib.llm import summarize_explanation

        try:
            e = summarize_explanation(
                catalyst,
                signal_kind,
                ticker=ticker,
                snippet=snippet,
                numbers=numbers,
            )
        except Exception:
            e = None
    if e is None:
        e = explain(catalyst, signal_kind)
    divider = "─" * 60
    what_block = f"What this means:\n{e.what}"
    if e.what_zh:
        what_block += f"\n\n内容:\n{e.what_zh}"
    why_block = f"Why it matters:\n{e.why}"
    if e.why_zh:
        why_block += f"\n\n影响:\n{e.why_zh}"
    return f"{body}\n{divider}\n{what_block}\n\n{why_block}\n"

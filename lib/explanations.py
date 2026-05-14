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
    what: str       # 1–2 sentences: what literally happened
    why: str        # 1–3 sentences: implication for the AI-infra thesis


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

# Composite registry: catalyst → signal_kind → Explanation
_REGISTRY: dict[str, dict[str, Explanation]] = {
    "C1": _C1,
    "C2": _C2,
    "C3": _C3,
    "C4": _C4,
    "C5": _C5,
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
    return (
        f"{body}\n"
        f"{divider}\n"
        f"What this means:\n{e.what}\n\n"
        f"Why it matters:\n{e.why}\n"
    )

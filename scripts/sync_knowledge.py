"""Verify stage: publish catalyst-tracker's sourced threshold facts to the corpus.

This is the WRITE half of the knowledge bridge (see ``lib/knowledge.py``). It mirrors
the cross-project pattern in ``<vault>/knowledge/README.md``: a project's verify stage
writes confirmed facts back to ``<vault>/knowledge/<domain>/`` so every other project's
pipeline can read them.

Each fact below is the exact alert-trigger condition for one catalyst, quoted verbatim
from ``docs/source-spec.md`` §10 and sourced to that section's permalink. Notes are
written as ``generated: verify-auto`` — re-running is idempotent and will refresh them
in place; any note a human marks ``manual: true`` is left untouched.

    .venv/bin/python -m scripts.sync_knowledge --dry-run   # preview, write nothing
    .venv/bin/python -m scripts.sync_knowledge             # publish into ai-infra/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import knowledge  # noqa: E402
from lib.knowledge import FactClaim  # noqa: E402

_SPEC = "https://github.com/cyprien0312/catalyst-tracker/blob/main/docs/source-spec.md"
_CLAUDE_MD = "https://github.com/cyprien0312/catalyst-tracker/blob/main/CLAUDE.md"


def _spec(fragment: str) -> str:
    return f"{_SPEC}#{fragment}"


# (slug, catalyst-tag, topic, src, verbatim-quote)
_FACTS: list[tuple[str, str, str, str, str]] = [
    (
        "c1-depreciation-useful-life",
        "c1",
        "C1 (GPU depreciation) fires when a hyperscaler's new 10-K/10-Q changes "
        "server/networking depreciation language (useful-life shortening or impairment).",
        _spec("c1-depreciation"),
        "new 10-K/10-Q filing for any of {MSFT, GOOGL, META, AMZN, ORCL, NVDA} "
        "(detected via SEC submissions JSON polling) AND filing text matches any of "
        "the 9 regex patterns in §3-C1",
    ),
    (
        "c2-neocloud-distress",
        "c2",
        "C2 (neocloud distress) fires on going-concern / covenant / distress 8-K items, "
        "a >=15% 1-day drop on 3x volume, sub-90c bond trades, or >=20% short interest.",
        _spec("c2-neocloud-distress"),
        "(new 10-K/10-Q matches `going concern OR material adverse OR covenant breach "
        "OR covenant default`) OR (new 8-K with item 2.04 / 4.02 / 1.03) OR (1-day stock "
        "close ≤ –15% AND volume ≥ 3× 20-day avg) OR (latest bond trade "
        "< 90 cents on dollar) OR (short interest ≥ 20% of float)",
    ),
    (
        "c3-openai-stress",
        "c3",
        "C3 (OpenAI stress) fires on OpenAI-keyword news/filings, and HIGH when an "
        "extracted burn-rate metric rises >25% QoQ.",
        _spec("c3-openai-stress"),
        "extracted numeric burn-rate metric increases >25% QoQ vs `c3_baselines` "
        "THEN alert HIGH",
    ),
    (
        "c4-capex-discipline",
        "c4",
        "C4 (hyperscaler capex) fires when TTM Capex/OCF crosses 110% upward vs the prior "
        "quarter, or TTM free cash flow turns negative.",
        _spec("c4-capex-cuts"),
        "TTM(Capex)/TTM(OCF) for any hyperscaler crosses 110% upward (vs prior quarter's "
        "value in `c4_xbrl`)",
    ),
    (
        "c5-grid-bottlenecks",
        "c5",
        "C5 (grid bottlenecks) fires on >=5 new >=100MW PJM withdrawals vs 7 days ago, a "
        ">=5% MoM ERCOT active-MW drop, or a Henry Hub 12-month strip avg >= $5.00.",
        _spec("c5-grid-bottlenecks"),
        "PJM queue snapshot diff vs 7-days-ago shows ≥ 5 new \"Withdrawn\" status "
        "changes for ≥100 MW projects OR ERCOT total active MW drops ≥ 5% MoM",
    ),
    (
        "c6-memory-storage-stress",
        "c6",
        "C6 (memory/storage stress) fires when an RSS item pairs a memory term "
        "(DRAM/NAND/HBM/...) with an order-cancellation, oversupply, or shortage tier "
        "token within 120 chars.",
        _spec("c6-memorystorage-price-stress"),
        "a new RSS item pairs a memory-subject term (`dram|nand|hbm|ddr[3-5]|flash memory|"
        "memory chip|memory price|ssd|hdd|hard drive`) with a tier token within 120 chars",
    ),
    (
        "c7-credit-stress",
        "c7",
        "C7 (credit stress) fires when HY/IG OAS widens >=75bp/>=30bp off its trailing-90 "
        "low, or sits at/above HY 400bp / IG 125bp absolute.",
        _spec("c7-credit-market-stress"),
        "HY or IG OAS (FRED) has widened ≥ trigger bp off its trailing-90-session low "
        "(HY +75bp / IG +30bp) OR the OAS is ≥ its absolute stress level "
        "(HY 400bp / IG 125bp)",
    ),
    (
        "c8-macro-inflation",
        "c8",
        "C8 (macro) fires when CPI YoY >= 3.5%, or CPI YoY has risen two consecutive months "
        "and is >= 3.0%.",
        _spec("c8-macro-triggers"),
        "CPI YoY ≥ 3.5% OR CPI YoY has risen for two consecutive months and is ≥ 3.0%",
    ),
    (
        "c9-crypto-cycle-top",
        "c9",
        "C9 (crypto cycle top) fires when BTC's Mayer Multiple (price/200DMA) >= 2.4, or the "
        "111DMA crosses above 2x the 350DMA (Pi Cycle Top).",
        _spec("c9-crypto-cycle-top"),
        "BTC Mayer Multiple (price/200DMA) ≥ 2.4 OR the 111DMA crosses above 2× the "
        "350DMA (Pi Cycle Top)",
    ),
    (
        "c10-liquidity-usd-realyield",
        "c10",
        "C10 (liquidity) mirrors C7 on the broad-USD index and 10y real yield via keyless "
        "FRED, escalating MED->HIGH at 2x the trigger off the trailing-90 low.",
        _CLAUDE_MD,
        "C10 mirrors C7's structure exactly (per-series config, trailing-90 low transition, "
        "MED→HIGH at 2× trigger)",
    ),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Publish tracker threshold facts to the knowledge corpus.")
    ap.add_argument("--dry-run", action="store_true", help="print planned writes, touch nothing")
    ap.add_argument("--domain", default=None, help="override domain folder (default: ai-infra)")
    ap.add_argument("--last-verified", default=None, help="ISO date stamp (default: today)")
    args = ap.parse_args(argv)

    dom = args.domain or knowledge.domain()
    root = knowledge.knowledge_dir() / dom
    print(f"knowledge dir: {root}  (domain={dom})")
    if args.dry_run:
        print("-- DRY RUN: no files written --")

    written = skipped = 0
    for slug, tag, topic, src, quote in _FACTS:
        claim = FactClaim(claim=topic, src=src, quote=quote)
        if args.dry_run:
            print(f"  would write {slug}.md  <- {src}")
            continue
        path = knowledge.write_fact(
            slug=slug,
            topic=topic,
            claims=[claim],
            tags=["ai-infra", tag],
            dom=dom,
            last_verified=args.last_verified,
        )
        if path is None:
            print(f"  skip   {slug}  (human-curated note owns this source)")
            skipped += 1
        else:
            print(f"  write  {path.name}")
            written += 1

    if not args.dry_run:
        print(f"done: {written} written, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

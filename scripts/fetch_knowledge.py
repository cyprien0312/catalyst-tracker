"""Fetch + verify live readings, then publish them to the knowledge corpus.

Thin CLI over ``lib/knowledge_fetch.py``. Pulls live HY/IG spreads, CPI / core-PCE,
the broad USD index, the 10y real yield, BTC's Mayer Multiple, the Nasdaq-100
drawdown, and the Henry Hub strip from the keyless FRED / CoinGecko / EIA sources,
verifies each (finite + in a plausibility band), and writes them into ``ai-infra/``.

    .venv/bin/python -m scripts.fetch_knowledge --dry-run   # fetch + verify, write nothing
    .venv/bin/python -m scripts.fetch_knowledge             # refresh the readings
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import knowledge, knowledge_fetch  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch + verify live readings into the knowledge corpus.")
    ap.add_argument("--dry-run", action="store_true", help="fetch + verify, but write nothing")
    ap.add_argument("--domain", default=None, help="override domain folder (default: ai-infra)")
    ap.add_argument("--last-verified", default=None, help="ISO date stamp (default: today)")
    args = ap.parse_args(argv)

    dom = args.domain or knowledge.domain()
    root = knowledge.knowledge_dir() / dom
    print(f"knowledge dir: {root}  (domain={dom})")

    readings = knowledge_fetch.gather()
    attempted = len(knowledge_fetch.PROBES)
    print(f"verified {len(readings)}/{attempted} probes:")
    for r in readings:
        print(f"  ✓ {r.slug:24s} {r.topic}")
    missing = attempted - len(readings)
    if missing:
        print(f"  ({missing} probe(s) skipped — fetch failed or out of band)")

    if args.dry_run:
        print("-- DRY RUN: no files written --")
        return 0

    written, skipped = knowledge_fetch.publish(
        readings, dom=dom, last_verified=args.last_verified
    )
    print(f"done: {written} written, {skipped} skipped (manual-owned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

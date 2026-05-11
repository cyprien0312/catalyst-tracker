"""Run all catalysts once for initial state seeding.

Usage:
    python scripts/backfill.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalysts.c1_depreciation import Catalyst1
from catalysts.c2_neoclouds import Catalyst2
from catalysts.c3_openai import Catalyst3
from catalysts.c4_capex import Catalyst4
from catalysts.c5_grid import Catalyst5

ALL_CATALYSTS = [
    ("c1", Catalyst1),
    ("c2", Catalyst2),
    ("c3", Catalyst3),
    ("c4", Catalyst4),
    ("c5", Catalyst5),
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="print alerts instead of emailing")
    p.add_argument("--only", help="comma-separated subset e.g. c1,c2")
    args = p.parse_args()

    wanted = set((args.only or "").split(",")) if args.only else None
    total = 0
    for cid, cls in ALL_CATALYSTS:
        if wanted and cid not in wanted:
            continue
        try:
            alerts = cls().run()
        except Exception as e:
            print(f"{cid}: failed with {e!r}")
            continue
        total += len(alerts)
        if args.dry_run:
            for a in alerts:
                print(f"[{cid}] {a.subject}")
        print(f"{cid}: {len(alerts)} alert(s)")
    print(f"backfill complete — {total} total alert(s) {'printed' if args.dry_run else 'emailed (or deduped)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

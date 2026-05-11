"""FINRA Fixed Income public bond display.

Note: FINRA's public bond detail pages are HTML and tend to restructure.
This module exposes a stable interface but currently returns None — wire-up
point for a future enhancement. Calls to it are non-fatal in catalysts.
"""
from __future__ import annotations


def latest_trade_price(symbol: str) -> float | None:
    """Return last bond trade price (cents on dollar) or None if unavailable.

    The public FINRA fixed-income display is delayed 4 hours and is fine
    for catalyst-style monitoring (not for intraday). This stub returns
    None pending a robust scraper.
    """
    return None

"""CoinGecko price client (keyless public API).

Used by C9 for Bitcoin cycle-top indicators (Mayer Multiple, Pi Cycle Top).
The public endpoint is rate-limited and may throttle server IPs; every call
degrades to [] on failure so the catalyst stays non-fatal.
"""
from __future__ import annotations

import requests

from lib.log import get_logger

log = get_logger(__name__)

BASE = "https://api.coingecko.com/api/v3"


def btc_daily_closes(days: int = 365, *, timeout: int = 30) -> list[tuple[int, float]]:
    """Return [(ts_ms, price_usd)] daily Bitcoin closes, ascending by time.

    Returns [] on any failure (network, rate-limit, schema change).
    """
    try:
        r = requests.get(
            f"{BASE}/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": "daily"},
            timeout=timeout,
        )
        r.raise_for_status()
    except requests.RequestException:
        log.exception("coingecko fetch failed")
        return []
    try:
        prices = r.json().get("prices", []) or []
    except ValueError:
        log.exception("coingecko returned non-JSON")
        return []
    out: list[tuple[int, float]] = []
    for pt in prices:
        if isinstance(pt, list) and len(pt) >= 2:
            try:
                out.append((int(pt[0]), float(pt[1])))
            except (ValueError, TypeError):
                continue
    return out

"""EIA open-data API client (free key)."""
from __future__ import annotations

import os
from typing import Optional

import requests

BASE = "https://api.eia.gov/v2"


def _key() -> Optional[str]:
    return os.environ.get("EIA_API_KEY")


def series(series_id: str, length: int = 30) -> list[dict]:
    """Return latest `length` observations for a series id (newest first).

    Returns [] if no key configured.
    """
    key = _key()
    if not key:
        return []
    url = f"{BASE}/seriesid/{series_id}"
    params = {"api_key": key, "length": length, "sort[0][column]": "period", "sort[0][direction]": "desc"}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"eia: fetch failed {series_id}: {e}")
        return []
    data = r.json().get("response", {})
    return data.get("data", []) or []


def henry_hub_strip() -> list[float]:
    """Front-month + futures contracts 2..12 (in USD/MMBtu). Returns [] if no key."""
    out: list[float] = []
    if not _key():
        return out
    for n in range(1, 13):
        rows = series(f"NG.RNGC{n}.D", length=1)
        if not rows:
            continue
        # rows[0] looks like {"period": "...", "value": "4.875", ...}
        try:
            out.append(float(rows[0].get("value")))
        except (TypeError, ValueError):
            continue
    return out

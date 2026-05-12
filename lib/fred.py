"""FRED API client (free key)."""
from __future__ import annotations

import os
from typing import Optional

import requests

from lib.log import get_logger

log = get_logger(__name__)

BASE = "https://api.stlouisfed.org/fred"


def _key() -> Optional[str]:
    return os.environ.get("FRED_API_KEY")


def observations(series_id: str, limit: int = 30) -> list[dict]:
    key = _key()
    if not key:
        return []
    try:
        r = requests.get(
            f"{BASE}/series/observations",
            params={"series_id": series_id, "api_key": key, "file_type": "json",
                    "sort_order": "desc", "limit": limit},
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException:
        log.exception("fred fetch failed %s", series_id)
        return []
    return r.json().get("observations", []) or []

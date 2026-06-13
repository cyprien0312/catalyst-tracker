"""FRED data client.

Two paths:
- `observations()` — JSON API, requires FRED_API_KEY.
- `series_csv()` — the keyless fredgraph.csv export, used by the credit/macro
  catalysts so they work without any secret configured.
"""
from __future__ import annotations

import csv
import io
import os
from typing import Optional

import requests

from lib.log import get_logger

log = get_logger(__name__)

BASE = "https://api.stlouisfed.org/fred"
GRAPH_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


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


def series_csv(series_id: str, *, timeout: int = 30) -> list[tuple[str, float]]:
    """Fetch a FRED series via the keyless CSV export.

    Returns [(date_str, value)] in ascending date order, skipping missing
    values (FRED encodes those as '.'). Returns [] on any failure — callers
    degrade gracefully, matching the rest of the tracker.
    """
    try:
        r = requests.get(GRAPH_CSV, params={"id": series_id}, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException:
        log.exception("fred csv fetch failed %s", series_id)
        return []
    out: list[tuple[str, float]] = []
    reader = csv.reader(io.StringIO(r.text))
    rows = list(reader)
    for row in rows[1:]:  # skip header (observation_date,<SERIES_ID>)
        if len(row) < 2:
            continue
        date_str, raw = row[0].strip(), row[1].strip()
        if not raw or raw == ".":
            continue
        try:
            out.append((date_str, float(raw)))
        except ValueError:
            continue
    return out

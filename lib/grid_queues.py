"""ISO interconnection queue downloaders."""
from __future__ import annotations

from io import BytesIO
from typing import Optional

import pandas as pd
import requests

HEADERS = {"User-Agent": "catalyst-tracker cyprien0312@gmail.com"}

PJM_QUEUE_URL = "https://services.pjm.com/PJMPlanningApi/api/Queues/ExportToExcel"
CAISO_QUEUE_URL = "https://www.caiso.com/documents/publicqueuereport.xlsx"


def _read_xlsx(url: str, timeout: int = 60) -> pd.DataFrame:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return pd.read_excel(BytesIO(r.content))


def pjm_active_queue() -> pd.DataFrame:
    return _read_xlsx(PJM_QUEUE_URL)


def caiso_queue() -> pd.DataFrame:
    return _read_xlsx(CAISO_QUEUE_URL)


def _coalesce_mw(df: pd.DataFrame) -> Optional[pd.Series]:
    """Return the most-likely MW column (varies by ISO)."""
    candidates = [
        "MW Capacity", "MW Energy", "MW", "Total Capacity", "Capacity (MW)",
        "Project MW", "Generating Facility Capacity"
    ]
    for col in candidates:
        if col in df.columns:
            try:
                return pd.to_numeric(df[col], errors="coerce")
            except Exception:
                continue
    return None


def summarize(df: pd.DataFrame, iso: str) -> dict:
    """Return summary stats for an ISO queue DataFrame.

    Returns {iso, count, total_mw, withdrawn_count, withdrawn_mw_100plus}.
    Schema-defensive: missing columns produce zeros, never crashes.
    """
    count = int(len(df))
    mw = _coalesce_mw(df)
    total_mw = float(mw.dropna().sum()) if mw is not None else 0.0

    status_col = None
    for c in ("Status", "status", "Project Status", "Queue Status"):
        if c in df.columns:
            status_col = c
            break

    withdrawn_count = 0
    withdrawn_mw_100plus = 0
    if status_col:
        statuses = df[status_col].astype(str).str.lower()
        withdrawn_mask = statuses.str.contains("withdraw|suspend|terminat", regex=True, na=False)
        withdrawn_count = int(withdrawn_mask.sum())
        if mw is not None:
            withdrawn_mw_100plus = int(((mw[withdrawn_mask] >= 100).fillna(False)).sum())

    return {
        "iso": iso,
        "count": count,
        "total_mw": total_mw,
        "withdrawn_count": withdrawn_count,
        "withdrawn_mw_100plus": withdrawn_mw_100plus,
    }

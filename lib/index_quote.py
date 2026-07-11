"""Index level + drawdown-from-ATH, for the NDX buy-plan signal.

Uses the same keyless FRED CSV path the credit/macro catalysts use, so it
needs no API key and degrades gracefully (returns None) on any failure.

The Nasdaq-100 (FRED id ``NASDAQ100``) is the ladder trigger — it is the
highest-beta, most AI-concentrated tell, so its drawdown from all-time high
drives the whole portfolio's accumulation ladder. The S&P 500 (FRED id
``SP500``) is rendered alongside as a reference line for the IVV/BGBL core
(an NDX -20% is typically only a -13..-15% on SPX).

Note the FRED keyless CSV serves roughly a trailing-10-year window, so "ATH"
here is the high within that window — identical for both series in practice.
"""
from __future__ import annotations

from typing import Callable, Optional

from lib.fred import series_csv

NDX_SERIES = "NASDAQ100"
SPX_SERIES = "SP500"

Fetch = Callable[[str], list[tuple[str, float]]]


def _drawdown(series_id: str, fetch: Optional[Fetch] = None) -> dict | None:
    """Current level, all-time high, and drawdown from that high for a FRED
    index series.

    ``fetch`` is injectable for tests; it must return ``[(date, value)]`` in
    ascending date order (same shape as :func:`lib.fred.series_csv`).

    Returns ``None`` if the series can't be fetched, so callers can skip the
    buy-plan block without breaking the rest of a report.
    """
    fetcher = fetch or series_csv
    series = fetcher(series_id)
    if not series or len(series) < 2:
        return None
    values = [v for _, v in series]
    current = values[-1]
    ath_idx = max(range(len(values)), key=lambda i: values[i])
    ath = values[ath_idx]
    if ath <= 0:
        return None
    return {
        "current": current,
        "date": series[-1][0],
        "ath": ath,
        "ath_date": series[ath_idx][0],
        "drawdown": current / ath - 1.0,  # negative when below ATH
    }


def ndx_drawdown(fetch: Optional[Fetch] = None) -> dict | None:
    return _drawdown(NDX_SERIES, fetch)


def spx_drawdown(fetch: Optional[Fetch] = None) -> dict | None:
    return _drawdown(SPX_SERIES, fetch)

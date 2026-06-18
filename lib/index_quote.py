"""Index level + drawdown-from-ATH, for the U100/NDX buy-plan signal.

Uses the same keyless FRED CSV path the credit/macro catalysts use, so it
needs no API key and degrades gracefully (returns None) on any failure.

The Nasdaq-100 (FRED id ``NASDAQ100``) is what the ASX:U100 ETF tracks, so its
drawdown from all-time high is the trigger ladder for accumulating U100.
"""
from __future__ import annotations

from typing import Callable, Optional

from lib.fred import series_csv

NDX_SERIES = "NASDAQ100"


def ndx_drawdown(
    fetch: Optional[Callable[[str], list[tuple[str, float]]]] = None,
) -> dict | None:
    """Return the current Nasdaq-100 level, its all-time high, and the
    drawdown from that high.

    ``fetch`` is injectable for tests; it must return ``[(date, value)]`` in
    ascending date order (same shape as :func:`lib.fred.series_csv`).

    Returns ``None`` if the series can't be fetched, so callers can skip the
    buy-plan block without breaking the rest of a report.
    """
    fetcher = fetch or series_csv
    series = fetcher(NDX_SERIES)
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

"""Stock price crash detector.

Wraps yfinance behind an injectable fetcher so tests don't hit the network.
"""
from __future__ import annotations

from typing import Callable, Optional

import pandas as pd


def _default_fetch(ticker: str) -> pd.DataFrame:
    import yfinance as yf
    return yf.Ticker(ticker).history(period="60d", interval="1d", auto_adjust=False)


def stock_crash(
    ticker: str,
    fetch: Optional[Callable[[str], pd.DataFrame]] = None,
    pct_threshold: float = -0.15,
    vol_ratio_threshold: float = 3.0,
) -> dict | None:
    """Return crash dict if latest session is a >=15% drop on >=3x average volume.

    Empty/short data returns None.
    """
    fetcher = fetch or _default_fetch
    df = fetcher(ticker)
    if df is None or len(df) < 21:
        return None
    closes = df["Close"]
    volumes = df["Volume"]
    last_close = float(closes.iloc[-1])
    prior_close = float(closes.iloc[-2])
    last_volume = float(volumes.iloc[-1])
    avg20 = float(volumes.iloc[-21:-1].mean())
    if prior_close <= 0 or avg20 <= 0:
        return None
    change_pct = (last_close - prior_close) / prior_close
    ratio = last_volume / avg20
    if change_pct <= pct_threshold and ratio >= vol_ratio_threshold:
        return {
            "ticker": ticker,
            "close": last_close,
            "prior_close": prior_close,
            "change_pct": change_pct,
            "volume": last_volume,
            "avg20": avg20,
            "ratio": ratio,
            "date": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1]),
        }
    return None

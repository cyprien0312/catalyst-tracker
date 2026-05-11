import pandas as pd
from lib.prices import stock_crash


def _df(closes, volumes):
    idx = pd.date_range("2025-01-01", periods=len(closes))
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=idx)


def test_no_data_returns_none():
    assert stock_crash("X", fetch=lambda t: pd.DataFrame()) is None


def test_normal_day_returns_none():
    closes = [100.0] * 30
    volumes = [1_000_000] * 30
    out = stock_crash("X", fetch=lambda t: _df(closes, volumes))
    assert out is None


def test_crash_detected():
    closes = [100.0] * 29 + [80.0]            # -20% last day
    volumes = [1_000_000] * 29 + [5_000_000]  # 5x volume
    out = stock_crash("X", fetch=lambda t: _df(closes, volumes))
    assert out is not None
    assert out["ticker"] == "X"
    assert out["change_pct"] < -0.15
    assert out["ratio"] >= 3.0


def test_big_drop_low_volume_does_not_fire():
    closes = [100.0] * 29 + [80.0]
    volumes = [1_000_000] * 30
    out = stock_crash("X", fetch=lambda t: _df(closes, volumes))
    assert out is None

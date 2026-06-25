from catalysts.c8_macro import Catalyst8, evaluate_cpi, evaluate_pce, _yoy_series
from lib.state import State


def _monthly(yoy_path, base=300.0):
    """Build a 24-month index series whose final YoY values follow yoy_path.

    Simplest construction: first 12 months flat at base, then months 13..24
    set so that month[i]/month[i-12] - 1 = yoy_path value.
    """
    series = [(f"2025-{m:02d}-01", base) for m in range(1, 13)]
    for i, yoy in enumerate(yoy_path):
        idx = base * (1 + yoy / 100.0)
        series.append((f"2026-{i+1:02d}-01", idx))
    return series


def test_yoy_computation():
    monthly = [(f"2025-{m:02d}-01", 100.0) for m in range(1, 13)] + [("2026-01-01", 104.0)]
    yoy = _yoy_series(monthly)
    assert yoy[-1][0] == "2026-01-01"
    assert abs(yoy[-1][1] - 4.0) < 1e-9


def test_cpi_hot_med():
    monthly = _monthly([3.8])  # 3.8% ≥ 3.5, < 4.5
    sigs = evaluate_cpi(monthly)
    hot = [s for s in sigs if s["kind"] == "CPI_HOT"][0]
    assert hot["severity"] == "MED"


def test_cpi_hot_high():
    monthly = _monthly([4.7])
    hot = [s for s in evaluate_cpi(monthly) if s["kind"] == "CPI_HOT"][0]
    assert hot["severity"] == "HIGH"


def test_cpi_reaccel():
    monthly = _monthly([3.1, 3.4, 3.7])  # rising 2 consecutive, ≥ 3.0
    sigs = evaluate_cpi(monthly)
    assert any(s["kind"] == "CPI_REACCEL" for s in sigs)


def test_no_reaccel_when_falling():
    monthly = _monthly([3.7, 3.4, 3.1])  # still ≥ 3.0 but falling
    sigs = evaluate_cpi(monthly)
    assert not any(s["kind"] == "CPI_REACCEL" for s in sigs)


def test_cool_cpi_no_signal():
    monthly = _monthly([2.0, 2.1, 2.2])  # below hot threshold and reaccel floor
    assert evaluate_cpi(monthly) == []


# --- core PCE (lower thresholds: hot ≥3.0, high ≥3.5, reaccel floor ≥2.5) ---

def test_pce_hot_med():
    monthly = _monthly([3.2])  # 3.2% ≥ 3.0, < 3.5
    hot = [s for s in evaluate_pce(monthly) if s["kind"] == "PCE_HOT"][0]
    assert hot["severity"] == "MED"


def test_pce_hot_high():
    monthly = _monthly([3.7])  # ≥ 3.5
    hot = [s for s in evaluate_pce(monthly) if s["kind"] == "PCE_HOT"][0]
    assert hot["severity"] == "HIGH"


def test_pce_reaccel():
    monthly = _monthly([2.6, 2.8, 3.1])  # rising 2 consecutive, ≥ 2.5
    assert any(s["kind"] == "PCE_REACCEL" for s in evaluate_pce(monthly))


def test_pce_cooler_than_cpi_thresholds():
    # 2.8% is hot for PCE (≥3.0? no) — verify a 2.8 print is NOT hot for PCE,
    # but 3.1 is. Guards against accidentally reusing the CPI threshold.
    assert not any(s["kind"] == "PCE_HOT" for s in evaluate_pce(_monthly([2.8])))
    assert any(s["kind"] == "PCE_HOT" for s in evaluate_pce(_monthly([3.1])))


def test_cpi_thresholds_unchanged_by_refactor():
    # 3.2% is hot for PCE but NOT for CPI (CPI hot floor is 3.5) — the shared
    # helper must keep CPI's stricter thresholds.
    assert not any(s["kind"] == "CPI_HOT" for s in evaluate_cpi(_monthly([3.2])))


# --- run() integration ---

def test_run_fires_and_dedups(tmp_path):
    monthly = _monthly([3.1, 3.4, 4.2])  # hot (HIGH? no, <4.5 → MED) + reaccel
    st = State("c8", db_path=tmp_path / "t.sqlite")
    cat = Catalyst8(state=st, fetch=lambda sid: monthly)
    first = cat.run()
    assert any(a.catalyst == "C8" for a in first)
    cat2 = Catalyst8(state=st, fetch=lambda sid: monthly)
    assert cat2.run() == []


def test_run_empty_no_crash(tmp_path):
    st = State("c8", db_path=tmp_path / "t.sqlite")
    cat = Catalyst8(state=st, fetch=lambda sid: [])
    assert cat.run() == []

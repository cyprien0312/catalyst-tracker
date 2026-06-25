from catalysts.c10_liquidity import Catalyst10, evaluate_series, SERIES
from lib.state import State

USD = SERIES["USD"]
REAL10 = SERIES["REAL10"]


# --- pure logic: USD (pct mode) ---

def test_no_signal_when_dollar_flat():
    assert evaluate_series([120.0] * 100, USD) == []


def test_dollar_surge_med():
    # ~+2.9% off the trailing low (120 → 123.5) → ≥ trigger (2.5%), < 2× (5%)
    values = [120.0] * 95 + [121.0, 121.8, 122.4, 123.0, 123.5]
    sigs = evaluate_series(values, USD)
    surge = [s for s in sigs if s["kind"] == "DOLLAR_SURGE"]
    assert len(surge) == 1
    assert surge[0]["severity"] == "MED"


def test_dollar_surge_high_at_double_trigger():
    # ~+5.8% off the low (120 → 127) ≥ 2× the 2.5% trigger
    values = [120.0] * 95 + [122.0, 123.5, 125.0, 126.0, 127.0]
    surge = [s for s in evaluate_series(values, USD) if s["kind"] == "DOLLAR_SURGE"][0]
    assert surge["severity"] == "HIGH"


# --- pure logic: real yield (level mode) ---

def test_real_yield_spike_med():
    # +40 bp off the low (1.80 → 2.20) → ≥ trigger (40bp), < 2× (80bp)
    values = [1.80] * 95 + [1.90, 2.00, 2.10, 2.15, 2.20]
    sigs = evaluate_series(values, REAL10)
    spike = [s for s in sigs if s["kind"] == "REAL_YIELD_SPIKE"]
    assert len(spike) == 1
    assert spike[0]["severity"] == "MED"


def test_real_yield_spike_high_at_double_trigger():
    # +90 bp off the low (1.50 → 2.40), ≥ 2× the 40bp trigger and < 2.50 stress
    values = [1.50] * 95 + [1.80, 2.05, 2.20, 2.30, 2.40]
    spike = [s for s in evaluate_series(values, REAL10) if s["kind"] == "REAL_YIELD_SPIKE"][0]
    assert spike["severity"] == "HIGH"


def test_real_yield_absolute_stress_high():
    # current ≥ 2.50% absolute restrictive level (flat, so no spike)
    values = [2.55] * 100
    sigs = evaluate_series(values, REAL10)
    assert any(s["kind"] == "REAL_YIELD_STRESS" and s["severity"] == "HIGH" for s in sigs)


def test_too_short_series_no_signal():
    assert evaluate_series([2.0], REAL10) == []


# --- run() integration ---

def _fake_fetch(mapping):
    def _f(series_id):
        vals = mapping.get(series_id, [])
        return [(f"2026-06-{(i % 28) + 1:02d}", v) for i, v in enumerate(vals)]
    return _f


def test_run_fires_and_dedups(tmp_path):
    usd = [120.0] * 95 + [121.0, 121.8, 122.4, 123.0, 123.5]
    fetch = _fake_fetch({"DTWEXBGS": usd, "DFII10": [1.50] * 100})
    st = State("c10", db_path=tmp_path / "t.sqlite")
    first = Catalyst10(state=st, fetch=fetch).run()
    assert any(a.catalyst == "C10" for a in first)
    assert Catalyst10(state=st, fetch=fetch).run() == []


def test_run_empty_no_crash(tmp_path):
    st = State("c10", db_path=tmp_path / "t.sqlite")
    cat = Catalyst10(state=st, fetch=lambda sid: [])
    assert cat.run() == []

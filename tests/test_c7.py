from catalysts.c7_credit import Catalyst7, evaluate_series, SERIES
from lib.state import State

HY = SERIES["HY"]
IG = SERIES["IG"]


# --- pure logic ---

def test_no_signal_when_flat_and_tight():
    values = [2.80] * 100  # flat HY, well below 4.00 stress
    assert evaluate_series(values, HY) == []


def test_widening_med():
    # 90d low ~2.80, current 2.80+0.80 = +80bp off low → ≥ trigger (75bp), < 2× (150bp)
    values = [2.80] * 95 + [3.10, 3.30, 3.50, 3.55, 3.60]
    sigs = evaluate_series(values, HY)
    widening = [s for s in sigs if s["kind"] == "SPREAD_WIDENING"]
    assert len(widening) == 1
    assert widening[0]["severity"] == "MED"


def test_widening_high_at_double_trigger():
    # +160bp off low ≥ 2× the 75bp trigger
    values = [2.80] * 95 + [3.5, 3.8, 4.1, 4.3, 4.40]
    sigs = evaluate_series(values, HY)
    widening = [s for s in sigs if s["kind"] == "SPREAD_WIDENING"][0]
    assert widening["severity"] == "HIGH"


def test_absolute_stress_high():
    values = [3.0] * 95 + [3.5, 3.8, 4.0, 4.1, 4.20]  # current ≥ 4.00
    sigs = evaluate_series(values, HY)
    assert any(s["kind"] == "SPREAD_STRESS" and s["severity"] == "HIGH" for s in sigs)


def test_ig_smaller_trigger():
    # IG widen trigger is 30bp; +35bp off low fires
    values = [0.75] * 95 + [0.85, 0.95, 1.05, 1.08, 1.10]
    sigs = evaluate_series(values, IG)
    assert any(s["kind"] == "SPREAD_WIDENING" for s in sigs)


def test_too_short_series_no_signal():
    assert evaluate_series([3.0], HY) == []


# --- run() integration ---

def _fake_fetch(mapping):
    def _f(series_id):
        vals = mapping.get(series_id, [])
        return [(f"2026-06-{(i % 28) + 1:02d}", v) for i, v in enumerate(vals)]
    return _f


def test_run_fires_and_dedups(tmp_path):
    hy = [2.80] * 95 + [3.10, 3.30, 3.50, 3.55, 3.60]
    fetch = _fake_fetch({"BAMLH0A0HYM2": hy, "BAMLC0A0CM": [0.75] * 100})
    st = State("c7", db_path=tmp_path / "t.sqlite")
    cat = Catalyst7(state=st, fetch=fetch)
    first = cat.run()
    assert any("widening" in a.subject.lower() and a.catalyst == "C7" for a in first)
    # Second run, same data/date → deduped.
    cat2 = Catalyst7(state=st, fetch=fetch)
    assert cat2.run() == []


def test_run_empty_series_no_crash(tmp_path):
    st = State("c7", db_path=tmp_path / "t.sqlite")
    cat = Catalyst7(state=st, fetch=lambda sid: [])
    assert cat.run() == []

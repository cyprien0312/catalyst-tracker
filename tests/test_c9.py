from catalysts.c9_crypto import Catalyst9, evaluate, _sma, MAYER_HOT
from lib.state import State


# --- _sma helper ---

def test_sma_basic():
    vals = [1.0, 2.0, 3.0, 4.0]
    assert _sma(vals, 2) == 3.5            # mean(3,4)
    assert _sma(vals, 2, offset=1) == 2.5  # mean(2,3)
    assert _sma(vals, 10) is None          # window longer than data


# --- Mayer Multiple ---

def test_mayer_none_when_below():
    closes = [100.0] * 200
    assert not any(s["kind"] == "MAYER_HOT" for s in evaluate(closes))


def test_mayer_med():
    closes = [100.0] * 199 + [250.0]  # Mayer ≈ 2.48
    sigs = [s for s in evaluate(closes) if s["kind"] == "MAYER_HOT"]
    assert len(sigs) == 1 and sigs[0]["severity"] == "MED"


def test_mayer_high():
    closes = [100.0] * 199 + [290.0]  # Mayer ≈ 2.87
    sigs = [s for s in evaluate(closes) if s["kind"] == "MAYER_HOT"]
    assert sigs[0]["severity"] == "HIGH"


def test_too_short_no_signal():
    assert evaluate([100.0] * 50) == []


# --- Pi Cycle Top ---

def test_pi_cycle_detects_cross_exactly_once():
    """A long flat history then a steep sustained uptrend makes the 111DMA
    cross above 2× the 350DMA on exactly one day."""
    full = [100.0] * 350 + [100.0 + 8 * i for i in range(1, 220)]
    fire_days = [
        n for n in range(360, len(full) + 1)
        if any(s["kind"] == "PI_CYCLE_TOP" for s in evaluate(full[:n]))
    ]
    assert len(fire_days) == 1  # transition fires once, not every day after


# --- run() integration ---

def _series_from_closes(closes):
    # CoinGecko shape: [(ts_ms, price)] one day apart.
    return [(1_700_000_000_000 + i * 86_400_000, p) for i, p in enumerate(closes)]


def test_run_mayer_fires_and_dedups(tmp_path):
    closes = [100.0] * 199 + [260.0]
    series = _series_from_closes(closes)
    st = State("c9", db_path=tmp_path / "t.sqlite")
    cat = Catalyst9(state=st, fetch=lambda: series)
    first = cat.run()
    assert any(a.catalyst == "C9" and "Mayer" in a.subject for a in first)
    cat2 = Catalyst9(state=st, fetch=lambda: series)
    assert cat2.run() == []


def test_run_insufficient_data_no_crash(tmp_path):
    st = State("c9", db_path=tmp_path / "t.sqlite")
    cat = Catalyst9(state=st, fetch=lambda: _series_from_closes([100.0] * 50))
    assert cat.run() == []


def test_run_empty_no_crash(tmp_path):
    st = State("c9", db_path=tmp_path / "t.sqlite")
    cat = Catalyst9(state=st, fetch=lambda: [])
    assert cat.run() == []

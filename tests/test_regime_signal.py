import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.index_quote import ndx_drawdown, spx_drawdown

_spec = importlib.util.spec_from_file_location(
    "regime_signal", _ROOT / "scripts" / "regime_signal.py")
rs = importlib.util.module_from_spec(_spec)
sys.modules["regime_signal"] = rs
_spec.loader.exec_module(rs)


# ---------- ndx_drawdown ----------

def test_ndx_drawdown_computes_from_ath():
    series = [("2026-01-01", 100.0), ("2026-02-01", 200.0), ("2026-03-01", 150.0)]
    got = ndx_drawdown(fetch=lambda _id: series)
    assert got["current"] == 150.0
    assert got["ath"] == 200.0
    assert got["ath_date"] == "2026-02-01"
    assert abs(got["drawdown"] - (-0.25)) < 1e-9


def test_ndx_drawdown_none_on_empty():
    assert ndx_drawdown(fetch=lambda _id: []) is None
    assert ndx_drawdown(fetch=lambda _id: [("d", 1.0)]) is None


def test_spx_drawdown_uses_sp500_series():
    seen_ids = []

    def fetch(series_id):
        seen_ids.append(series_id)
        return [("2026-01-01", 5000.0), ("2026-02-01", 4500.0)]

    got = spx_drawdown(fetch=fetch)
    assert seen_ids == ["SP500"]
    assert abs(got["drawdown"] - (-0.10)) < 1e-9


# ---------- regime selection ----------

def _ndx(dd, ath=30000.0):
    return {"current": ath * (1 + dd), "date": "2026-06-17",
            "ath": ath, "ath_date": "2026-06-01", "drawdown": dd}


def test_regime_a_when_no_fuse():
    plan = rs.build_plan(_ndx(-0.03), fuse_lit=False, fuses=[])
    assert plan["regime"] == rs.A
    # only the starter rung triggered at -3%
    assert plan["cumulative_target"] == 10
    assert plan["reserve"] == 40
    assert plan["next_rung"]["thresh"] == -0.10


def test_regime_a_ladder_accumulates_with_drawdown():
    plan = rs.build_plan(_ndx(-0.17), fuse_lit=False, fuses=[])
    # deep-heavy ladder: starter(10) + dip1(10) + dip2(15) at -17%, dip3 not yet
    assert plan["cumulative_target"] == 35
    assert plan["next_rung"]["thresh"] == -0.20


def test_regime_a_full_ladder_deploys_60():
    plan = rs.build_plan(_ndx(-0.25), fuse_lit=False, fuses=[])
    assert plan["cumulative_target"] == 60
    assert plan["reserve"] == 40


def test_fuse_flips_to_regime_b():
    plan = rs.build_plan(_ndx(-0.12), fuse_lit=True, fuses=["C7"])
    assert plan["regime"] == rs.B
    assert plan["fuses"] == ["C7"]
    # shallow ladder is frozen — nothing triggered until -30%
    assert plan["cumulative_target"] == 0
    assert plan["next_rung"]["thresh"] == -0.30


def test_regime_b_deep_needs_stabilisation():
    shallow = rs.build_plan(_ndx(-0.35), fuse_lit=True, fuses=["C2"])
    assert shallow["needs_stabilisation"] is False
    deep = rs.build_plan(_ndx(-0.55), fuse_lit=True, fuses=["C2"])
    assert deep["needs_stabilisation"] is True
    assert deep["cumulative_target"] == 40  # all three B rungs


def test_build_plan_none_when_no_quote():
    assert rs.build_plan(None, fuse_lit=False, fuses=[]) is None


# ---------- rendering smoke ----------

def test_render_text_contains_levels_and_regime():
    out = rs.render_text(rs.build_plan(_ndx(-0.03), False, []))
    assert "BUY PLAN" in out and "Regime A" in out and "NDX" in out
    assert "SPX" not in out  # no reference line when spx is absent


def _spx(dd, ath=6000.0):
    return {"current": ath * (1 + dd), "date": "2026-06-17",
            "ath": ath, "ath_date": "2026-06-01", "drawdown": dd}


def test_render_includes_spx_reference_line():
    plan = rs.build_plan(_ndx(-0.12), False, [], spx=_spx(-0.08))
    assert plan["spx"]["drawdown"] == -0.08
    text = rs.render_text(plan)
    assert "SPX 5,520" in text and "-8.0%" in text
    card = rs.render_html_card(plan)
    assert "SPX 5,520" in card and "IVV/BGBL" in card


def test_render_html_card_empty_when_none():
    assert rs.render_html_card(None) == ""
    card = rs.render_html_card(rs.build_plan(_ndx(-0.55), True, ["C7"]))
    assert "BUY PLAN" in card and "frozen" in card.lower()

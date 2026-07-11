import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.state import State

_spec_rs = importlib.util.spec_from_file_location(
    "regime_signal", _ROOT / "scripts" / "regime_signal.py")
rs = importlib.util.module_from_spec(_spec_rs)
sys.modules["regime_signal"] = rs
_spec_rs.loader.exec_module(rs)

_spec_ra = importlib.util.spec_from_file_location(
    "rung_alert", _ROOT / "scripts" / "rung_alert.py")
ra = importlib.util.module_from_spec(_spec_ra)
sys.modules["rung_alert"] = ra
_spec_ra.loader.exec_module(ra)


def _ndx(dd, ath=30000.0, ath_date="2026-06-01"):
    return {"current": ath * (1 + dd), "date": "2026-06-17",
            "ath": ath, "ath_date": ath_date, "drawdown": dd}


def _state(tmp_path):
    return State("rung_alert", db_path=tmp_path / "t.sqlite")


# ---------- new_crossings ----------

def test_starter_rung_never_alerts(tmp_path):
    plan = rs.build_plan(_ndx(-0.03), False, [])
    assert ra.new_crossings(plan, _state(tmp_path)) == []


def test_crossed_rungs_alert_once_per_episode(tmp_path):
    st = _state(tmp_path)
    plan = rs.build_plan(_ndx(-0.17), False, [])
    got = ra.new_crossings(plan, st)
    assert [r["thresh"] for r in got] == [-0.10, -0.15]
    for r in got:
        st.mark_seen(ra.RUNG_TABLE, r["key"])
    # same episode: nothing new; deeper drawdown surfaces only the new rung
    assert ra.new_crossings(plan, st) == []
    deeper = rs.build_plan(_ndx(-0.22), False, [])
    assert [r["thresh"] for r in ra.new_crossings(deeper, st)] == [-0.20]


def test_new_ath_rearms_rungs(tmp_path):
    st = _state(tmp_path)
    plan = rs.build_plan(_ndx(-0.12), False, [])
    for r in ra.new_crossings(plan, st):
        st.mark_seen(ra.RUNG_TABLE, r["key"])
    # recovery to a new ATH, then a fresh -12% episode
    again = rs.build_plan(_ndx(-0.12, ath=35000.0, ath_date="2026-09-01"), False, [])
    assert [r["thresh"] for r in ra.new_crossings(again, st)] == [-0.10]


def test_regime_b_uses_deep_ladder_keys(tmp_path):
    st = _state(tmp_path)
    plan = rs.build_plan(_ndx(-0.35), True, ["C7"])
    got = ra.new_crossings(plan, st)
    assert [r["thresh"] for r in got] == [-0.30]
    assert got[0]["key"].startswith("B:")


# ---------- previous_regime ----------

def test_previous_regime_roundtrip(tmp_path):
    st = _state(tmp_path)
    assert ra.previous_regime(st) is None
    st.mark_seen(ra.REGIME_TABLE, "A")
    assert ra.previous_regime(st) == "A"


# ---------- alert content ----------

def test_rung_alert_content_regime_a(tmp_path):
    plan = rs.build_plan(_ndx(-0.17), False, [])
    rung = ra.new_crossings(plan, _state(tmp_path))[1]
    subject, body, severity = ra.rung_alert_content(plan, rung)
    assert severity == "HIGH"
    assert "[BUYPLAN]" in subject and "dip 2" in subject and "15%" in subject
    assert "BUY PLAN" in body  # full ladder embedded


def test_deep_rung_requires_stabilisation_note():
    plan = rs.build_plan(_ndx(-0.55), True, ["C7"])
    deep = [r for r in plan["rungs"] if r["thresh"] == -0.50][0]
    subject, body, _ = ra.rung_alert_content(plan, {**deep, "key": "k"})
    assert "stabilisation" in subject


def test_flip_alert_severity():
    plan_b = rs.build_plan(_ndx(-0.12), True, ["C7"])
    subject, _, severity = ra.flip_alert_content(plan_b, "A")
    assert severity == "CRITICAL" and "A → B" in subject and "FREEZE" in subject
    plan_a = rs.build_plan(_ndx(-0.12), False, [])
    _, _, severity_a = ra.flip_alert_content(plan_a, "B")
    assert severity_a == "MED"


# ---------- run() end-to-end ----------

def test_run_sends_and_marks(tmp_path, monkeypatch):
    st = _state(tmp_path)
    sent = []
    monkeypatch.setattr(ra, "send_alert",
                        lambda subject, body, severity, catalyst, state: sent.append(subject) or True)
    monkeypatch.setattr(ra.regime_signal, "live_plan",
                        lambda: rs.build_plan(_ndx(-0.17), False, []))
    assert ra.run(state=st) == 0
    assert len(sent) == 2  # dip1 + dip2; first run records regime silently
    sent.clear()
    assert ra.run(state=st) == 0
    assert sent == []  # idempotent
    # fuse fires -> flip alert only (deep rungs not yet crossed at -17%)
    monkeypatch.setattr(ra.regime_signal, "live_plan",
                        lambda: rs.build_plan(_ndx(-0.17), True, ["C7"]))
    assert ra.run(state=st) == 0
    assert len(sent) == 1 and "A → B" in sent[0]


def test_run_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    st = _state(tmp_path)
    monkeypatch.setattr(ra, "send_alert",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("emailed in dry-run")))
    monkeypatch.setattr(ra.regime_signal, "live_plan",
                        lambda: rs.build_plan(_ndx(-0.17), False, []))
    assert ra.run(dry_run=True, state=st) == 0
    assert "[BUYPLAN]" in capsys.readouterr().out
    assert ra.previous_regime(st) is None  # no state writes
    assert ra.new_crossings(rs.build_plan(_ndx(-0.17), False, []), st) != []


def test_run_degrades_when_index_fetch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ra.regime_signal, "live_plan", lambda: None)
    assert ra.run(state=_state(tmp_path)) == 0

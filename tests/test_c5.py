import pandas as pd

from catalysts.c5_grid import Catalyst5
from lib.grid_queues import summarize
from lib.state import State


def _df(rows, mw_col="MW Capacity", status_col="Status"):
    return pd.DataFrame(rows)


def test_summarize_handles_missing_columns():
    df = pd.DataFrame({"foo": [1, 2, 3]})
    s = summarize(df, "PJM")
    assert s["count"] == 3 and s["total_mw"] == 0 and s["withdrawn_count"] == 0


def test_summarize_counts_withdrawals():
    df = pd.DataFrame({
        "MW Capacity": [200, 50, 300, 400, 100],
        "Status": ["Active", "Withdrawn", "Active", "Suspended", "Withdrawn"],
    })
    s = summarize(df, "PJM")
    assert s["count"] == 5
    assert s["withdrawn_count"] == 3  # withdrawn or suspended
    assert s["withdrawn_mw_100plus"] == 2  # 400 and 100; not 50


def test_run_alerts_on_mw_drop(tmp_path):
    big = pd.DataFrame({"MW Capacity": [1000] * 20, "Status": ["Active"] * 20})
    small = pd.DataFrame({"MW Capacity": [800] * 20, "Status": ["Active"] * 20})

    st = State("c5", db_path=tmp_path / "t.sqlite")
    # First run with PJM=big to seed history.
    cat = Catalyst5(state=st, fetch_pjm=lambda: big, fetch_caiso=lambda: pd.DataFrame(),
                    fetch_henryhub=lambda: [])
    cat.run()

    # Manipulate stored snapshot to be in the past so the second run is "today".
    import datetime as dt
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    with st.connection() as c:
        c.execute("UPDATE c5_queues SET snapshot_date=? WHERE snapshot_date=?",
                  (yesterday, dt.date.today().isoformat()))

    cat2 = Catalyst5(state=st, fetch_pjm=lambda: small, fetch_caiso=lambda: pd.DataFrame(),
                     fetch_henryhub=lambda: [])
    alerts = cat2.run()
    drop_alerts = [a for a in alerts if "MW down" in a.subject]
    assert len(drop_alerts) == 1


def test_henry_hub_stress_fires(tmp_path):
    st = State("c5", db_path=tmp_path / "t.sqlite")
    cat = Catalyst5(state=st,
                    fetch_pjm=lambda: pd.DataFrame(),
                    fetch_caiso=lambda: pd.DataFrame(),
                    fetch_henryhub=lambda: [5.50, 5.20, 5.00, 5.10, 4.95, 5.05, 5.00, 5.10, 5.20, 5.00, 4.90, 5.10])
    alerts = cat.run()
    assert any("Henry Hub" in a.subject for a in alerts)


def test_henry_hub_no_data_no_crash(tmp_path):
    st = State("c5", db_path=tmp_path / "t.sqlite")
    cat = Catalyst5(state=st,
                    fetch_pjm=lambda: pd.DataFrame(),
                    fetch_caiso=lambda: pd.DataFrame(),
                    fetch_henryhub=lambda: [])
    assert cat.run() == []


def test_pjm_404_does_not_block_caiso_or_henry_hub(tmp_path):
    """If PJM raises, C5 must still attempt CAISO and Henry Hub paths."""
    from requests.exceptions import HTTPError

    calls = {"caiso": 0, "henry": 0}

    def boom_pjm():
        raise HTTPError("404 PJM")

    def fake_caiso():
        calls["caiso"] += 1
        return pd.DataFrame()

    def fake_henry():
        calls["henry"] += 1
        return [5.50] * 12  # crosses HENRY_HUB_STRESS threshold

    st = State("c5", db_path=tmp_path / "t.sqlite")
    cat = Catalyst5(state=st,
                    fetch_pjm=boom_pjm,
                    fetch_caiso=fake_caiso,
                    fetch_henryhub=fake_henry)
    alerts = cat.run()  # must not raise

    assert calls["caiso"] >= 1, "CAISO must run even after PJM failure"
    assert calls["henry"] >= 1, "Henry Hub must run even after PJM failure"
    assert any("Henry Hub" in a.subject for a in alerts), \
        "Henry Hub alert should still fire when PJM is broken"


def test_henry_hub_exception_does_not_break_run(tmp_path):
    """If Henry Hub fetch raises, run() should still return cleanly."""
    def boom():
        raise RuntimeError("EIA down")

    st = State("c5", db_path=tmp_path / "t.sqlite")
    cat = Catalyst5(state=st,
                    fetch_pjm=lambda: pd.DataFrame(),
                    fetch_caiso=lambda: pd.DataFrame(),
                    fetch_henryhub=boom)
    assert cat.run() == []

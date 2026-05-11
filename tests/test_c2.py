from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from catalysts.c2_neoclouds import Catalyst2, scan_text
from lib.edgar import Filing
from lib.state import State

FIX = Path(__file__).parent / "fixtures"


def _filing(cik, acc, form, primary="x.htm", items=()):
    return Filing(
        cik=cik, accession=acc, form=form, filed_date="2025-04-09",
        primary_document=primary,
        url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-','')}/{primary}",
        items=items,
    )


def test_going_concern_regex_matches_fixture():
    text = (FIX / "apld_10q_going_concern.txt").read_text()
    hits = scan_text(text)
    keys = {h["key"] for h in hits}
    assert "GOING_CONCERN" in keys
    assert "COVENANT_DISTRESS" in keys
    severities = [h["severity"] for h in hits]
    assert "CRITICAL" in severities


def test_decoy_text_no_hits():
    assert scan_text("Property and equipment, net of depreciation, $1B.") == []


def test_run_emits_filing_alert(tmp_path):
    text = (FIX / "apld_10q_going_concern.txt").read_text()
    edgar = MagicMock()
    edgar.recent_filings.side_effect = lambda cik, forms, limit=20: (
        [_filing("0001144879", "0001628280-25-017684", "10-Q")] if cik == "0001144879" else []
    )
    edgar.get_filing_text.return_value = text

    st = State("c2", db_path=tmp_path / "t.sqlite")
    cat = Catalyst2(
        edgar=edgar, state=st,
        price_fetch=lambda t: pd.DataFrame(),  # disable crash detector
    )
    alerts = cat.run()
    apld = [a for a in alerts if "APLD" in a.subject]
    assert len(apld) == 1
    assert apld[0].severity == "CRITICAL"


def test_run_emits_8k_item_alert(tmp_path):
    edgar = MagicMock()
    edgar.recent_filings.side_effect = lambda cik, forms, limit=20: (
        [_filing("0001144879", "0001628280-25-000999", "8-K", items=("2.04", "7.01"))]
        if cik == "0001144879" else []
    )
    st = State("c2", db_path=tmp_path / "t.sqlite")
    cat = Catalyst2(
        edgar=edgar, state=st,
        price_fetch=lambda t: pd.DataFrame(),
    )
    alerts = cat.run()
    apld = [a for a in alerts if "APLD" in a.subject and "8-K" in a.subject]
    assert len(apld) == 1
    assert apld[0].severity == "CRITICAL"
    assert "2.04" in apld[0].subject


def test_run_idempotent(tmp_path):
    edgar = MagicMock()
    edgar.recent_filings.side_effect = lambda cik, forms, limit=20: (
        [_filing("0001144879", "0001628280-25-017684", "10-Q")] if cik == "0001144879" else []
    )
    edgar.get_filing_text.return_value = (FIX / "apld_10q_going_concern.txt").read_text()

    st = State("c2", db_path=tmp_path / "t.sqlite")
    cat = Catalyst2(edgar=edgar, state=st, price_fetch=lambda t: pd.DataFrame())
    first = cat.run()
    second = cat.run()
    assert len(first) == 1 and second == []


def test_run_emits_crash_alert(tmp_path):
    # No filings, but a crash
    edgar = MagicMock()
    edgar.recent_filings.side_effect = lambda cik, forms, limit=20: []

    idx = pd.date_range("2025-01-01", periods=30)
    closes = [100.0] * 29 + [80.0]
    volumes = [1_000_000] * 29 + [5_000_000]
    df = pd.DataFrame({"Close": closes, "Volume": volumes}, index=idx)

    st = State("c2", db_path=tmp_path / "t.sqlite")
    cat = Catalyst2(
        edgar=edgar, state=st,
        watchlist={"CRWV": "0001769628"},
        price_fetch=lambda t: df,
    )
    alerts = cat.run()
    assert len(alerts) == 1
    a = alerts[0]
    assert a.catalyst == "C2" and a.severity == "HIGH"
    assert "CRWV" in a.subject

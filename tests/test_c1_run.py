from pathlib import Path
from unittest.mock import MagicMock
from catalysts.c1_depreciation import Catalyst1
from lib.edgar import Filing
from lib.state import State

FIX = Path(__file__).parent / "fixtures"


def _filing(cik, acc, form="10-K", primary="x.htm"):
    return Filing(
        cik=cik, accession=acc, form=form, filed_date="2025-02-07",
        primary_document=primary,
        url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-','')}/{primary}",
    )


def test_run_emits_alert_when_filing_matches(tmp_path):
    text = (FIX / "amzn_2024_10k_excerpt.txt").read_text()
    edgar = MagicMock()

    def recent(cik, forms, limit=20):
        if cik == "0001018724":
            return [_filing("0001018724", "0001018724-25-000004")]
        return []

    edgar.recent_filings.side_effect = recent
    edgar.get_filing_text.return_value = text

    st = State("c1", db_path=tmp_path / "t.sqlite")
    cat = Catalyst1(edgar=edgar, state=st)
    alerts = cat.run()
    assert len(alerts) == 1
    a = alerts[0]
    assert a.catalyst == "C1"
    assert a.severity == "HIGH"
    assert "AMZN" in a.subject and "10-K" in a.subject
    assert "0001018724-25-000004" in a.body
    assert "AMZN_SUBSET_PHRASE" in a.body or "USEFUL_LIFE_SHORTENED_6_TO_5" in a.body
    # Explanation context appended
    assert "What this means:" in a.body
    assert "Why it matters:" in a.body


def test_run_skips_already_seen_filings(tmp_path):
    edgar = MagicMock()
    edgar.recent_filings.side_effect = lambda cik, forms, limit=20: (
        [_filing("0001018724", "0001018724-25-000004")] if cik == "0001018724" else []
    )
    edgar.get_filing_text.return_value = (FIX / "amzn_2024_10k_excerpt.txt").read_text()

    st = State("c1", db_path=tmp_path / "t.sqlite")
    cat = Catalyst1(edgar=edgar, state=st)
    first = cat.run()
    assert len(first) == 1
    second = cat.run()
    assert second == []
    assert edgar.get_filing_text.call_count == 1


def test_run_emits_no_alert_when_no_match(tmp_path):
    edgar = MagicMock()
    edgar.recent_filings.side_effect = lambda cik, forms, limit=20: (
        [_filing("0001018724", "0001018724-25-000999")] if cik == "0001018724" else []
    )
    edgar.get_filing_text.return_value = (FIX / "decoy_useful_life.txt").read_text()

    st = State("c1", db_path=tmp_path / "t.sqlite")
    cat = Catalyst1(edgar=edgar, state=st)
    assert cat.run() == []
    assert st.seen("c1_filings", "0001018724-25-000999") is True

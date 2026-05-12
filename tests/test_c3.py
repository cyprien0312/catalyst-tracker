from unittest.mock import MagicMock
import pytest
import responses
from pathlib import Path

from catalysts.c3_openai import Catalyst3, classify
from lib.state import State

FIX = Path(__file__).parent / "fixtures"


def test_classify_critical():
    assert classify("OpenAI files bond prospectus") == "CRITICAL"


def test_classify_high():
    assert classify("OpenAI burn rate accelerates") == "HIGH"


def test_classify_med():
    assert classify("Sarah Friar joins OpenAI as CFO") == "MED"


def test_classify_returns_none_without_openai_mention():
    assert classify("Bond market turmoil hits tech") is None


def test_classify_returns_none_without_tier_token():
    assert classify("OpenAI launches new product") is None


def test_classify_chatgpt_counts_as_openai():
    assert classify("ChatGPT down round expected") == "HIGH"


# --- false-positive regression tests (the reason we added proximity) ---

def test_msft_10q_unrelated_impair_does_not_fire():
    """The exact FP we saw in production: 10-Q mentions OpenAI in one section
    and 'impairment of goodwill' hundreds of chars away in an unrelated PP&E
    discussion. The classifier must NOT fire CRITICAL on that."""
    text = (
        "We maintain a strategic relationship with OpenAI. "
        + ("Lorem ipsum dolor sit amet. " * 30)  # ~840 chars of filler
        + "Impairment of goodwill totaled $X million for the period."
    )
    assert classify(text) is None  # too far apart


def test_msft_10q_openai_writedown_does_fire():
    """The TRUE positive: OpenAI mentioned right next to a write-down."""
    text = "We recorded a write-down on our OpenAI equity investment."
    assert classify(text) == "CRITICAL"


def test_news_headline_with_close_proximity_fires():
    text = "OpenAI faces covenant breach, sources say"
    assert classify(text) == "CRITICAL"


def test_lowercase_ipo_inside_other_word_does_not_match():
    # "iponomy", "champion" — should not trip "IPO".
    text = "OpenAI champion of AI faces iponomic pressure"
    assert classify(text) is None


def test_uppercase_IPO_does_match():
    text = "OpenAI IPO timeline shifts"
    assert classify(text) == "HIGH"


def test_sarah_friar_lowercase_does_not_match():
    """Sarah Friar is proper-noun; lowercase should not match (avoids accidental
    matches inside other words like 'friars')."""
    text = "openai sarah friar speaks at event"  # all lowercase
    assert classify(text) is None


def test_default_substring_inside_word_does_not_fire():
    """Old token 'default' was a bare substring — 'defaulted' fired but so did
    legitimate uses. Verify our word-bounded regex still catches 'default'
    forms but rejects substring matches."""
    assert classify("OpenAI debt defaulted on Tuesday") == "CRITICAL"
    # 'default' inside "defaultable" is still a word boundary match — that's fine.


@responses.activate
def test_run_returns_news_alerts(tmp_path):
    body = (FIX / "sample_feed.xml").read_text()
    feed_url = "http://example.com/sample.xml"
    responses.add(responses.GET, feed_url, body=body, status=200)

    edgar = MagicMock()
    edgar.recent_filings.return_value = []  # skip filings

    st = State("c3", db_path=tmp_path / "t.sqlite")
    cat = Catalyst3(edgar=edgar, state=st, feeds=[feed_url])
    alerts = cat.run()
    # Two items in the feed; first is CRITICAL (bond prospectus),
    # second is MED (Sarah Friar + revenue).
    sevs = sorted(a.severity for a in alerts)
    assert "CRITICAL" in sevs
    assert "MED" in sevs


@responses.activate
def test_run_dedups_seen_entries(tmp_path):
    body = (FIX / "sample_feed.xml").read_text()
    feed_url = "http://example.com/sample.xml"
    responses.add(responses.GET, feed_url, body=body, status=200)
    responses.add(responses.GET, feed_url, body=body, status=200)

    edgar = MagicMock()
    edgar.recent_filings.return_value = []

    st = State("c3", db_path=tmp_path / "t.sqlite")
    cat = Catalyst3(edgar=edgar, state=st, feeds=[feed_url])
    first = cat.run()
    second = cat.run()
    assert len(first) >= 1
    assert second == []

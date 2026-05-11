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

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


def test_uppercase_IPO_matches_as_med():
    # IPO is a context token, not a stress signal — daily news, not actionable.
    text = "OpenAI IPO timeline shifts"
    assert classify(text) == "MED"


def test_net_loss_is_med_not_high():
    # "net loss" gets quoted in every OpenAI recap; demoted to MED.
    assert classify("OpenAI net loss widened in Q2") == "MED"


def test_down_round_remains_high():
    assert classify("OpenAI down round expected") == "HIGH"


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


def test_default_chatgpt_is_not_critical():
    """'default ChatGPT' / 'default mode' must NOT fire CRITICAL — the word
    'default' there is an adjective, not a debt default."""
    assert classify("Is OpenAI's lockdown mode an admission that default ChatGPT was unsafe?") is None
    assert classify("OpenAI changes the default model for free users") is None


def test_real_debt_default_still_critical():
    assert classify("OpenAI defaulted on its debt") == "CRITICAL"
    assert classify("OpenAI bond covenant default") == "CRITICAL"


def test_ipo_prospectus_not_critical():
    """IPO prospectus is MED-tier chatter, not distress; only a bond prospectus
    (via the 'bond' token) is CRITICAL."""
    assert classify("OpenAI files confidential IPO prospectus") == "MED"  # IPO token
    assert classify("OpenAI bond prospectus filed") == "CRITICAL"


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


def test_primary_source_detection():
    from catalysts.c3_openai import _is_primary_source
    assert _is_primary_source("https://feeds.bloomberg.com/technology/news.rss")
    assert _is_primary_source("https://feeds.content.dowjones.io/public/rss/RSSWSJD")
    assert not _is_primary_source(
        "https://news.google.com/rss/search?q=OpenAI+when:1d"
    )


@responses.activate
def test_high_from_google_news_downgrades_to_med(tmp_path):
    # A HIGH-tier keyword in a Google News headline should arrive as MED
    # because Google News is not a primary source.
    feed_url = "https://news.google.com/rss/search?q=OpenAI"
    body = """<?xml version="1.0"?><rss version="2.0"><channel>
<title>x</title><link>http://x</link><description>x</description>
<item><title>OpenAI down round rumored</title>
<link>http://example.com/a</link>
<description>OpenAI down round rumored as costs mount</description>
<guid>a1</guid><pubDate>Tue, 12 May 2026 00:00:00 GMT</pubDate>
</item></channel></rss>"""
    responses.add(responses.GET, feed_url, body=body, status=200)

    edgar = MagicMock()
    edgar.recent_filings.return_value = []
    st = State("c3", db_path=tmp_path / "t.sqlite")
    cat = Catalyst3(edgar=edgar, state=st, feeds=[feed_url])
    alerts = cat.run()
    assert len(alerts) == 1
    assert alerts[0].severity == "MED"


@responses.activate
def test_high_from_bloomberg_stays_high(tmp_path):
    feed_url = "https://feeds.bloomberg.com/technology/news.rss"
    body = """<?xml version="1.0"?><rss version="2.0"><channel>
<title>x</title><link>http://x</link><description>x</description>
<item><title>OpenAI down round rumored</title>
<link>http://bloomberg.com/a</link>
<description>OpenAI down round rumored as costs mount</description>
<guid>b1</guid><pubDate>Tue, 12 May 2026 00:00:00 GMT</pubDate>
</item></channel></rss>"""
    responses.add(responses.GET, feed_url, body=body, status=200)

    edgar = MagicMock()
    edgar.recent_filings.return_value = []
    st = State("c3", db_path=tmp_path / "t.sqlite")
    cat = Catalyst3(edgar=edgar, state=st, feeds=[feed_url])
    alerts = cat.run()
    assert len(alerts) == 1
    assert alerts[0].severity == "HIGH"


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


# --- sense guards on the CRITICAL tier -------------------------------------
# Verbatim headlines from the alerts table. CRITICAL is the only C3 tier that
# e-mails, and 5 of the 9 CRITICALs ever raised were false positives.

def test_org_restructuring_is_not_financial_distress():
    for t in [
        "OpenAI in talks to give US government 5% stake, say reports; Starling to cut 130 roles in AI-driven restructuring",
        "OpenAI's Head of Safety Johannes Heidecke Exits Amid Restructuring",
    ]:
        assert classify(t) != "CRITICAL", t


def test_default_as_a_setting_is_not_a_debt_event():
    t = ("'We don't believe this kind of government access process should become "
         "the long-term default': OpenAI's new AI models have a very unusual feature")
    assert classify(t) != "CRITICAL"


def test_real_debt_default_still_critical():
    assert classify("OpenAI defaulted on a $2bn loan payment to its lenders") == "CRITICAL"


def test_real_debt_restructuring_still_critical():
    assert classify(
        "OpenAI begins debt restructuring talks with creditors over its credit facility"
    ) == "CRITICAL"


def test_genuine_bond_headlines_survive():
    for t in [
        "S&P Downgrades Oracle's Bond Rating, Names OpenAI as a “Credit Risk”",
        "SoftBank Seeks 60 Billion Bond Sale Amid Nearly $65 Billion OpenAI Commitment",
    ]:
        assert classify(t) == "CRITICAL", t

import responses

from catalysts.c6_memory import Catalyst6, classify
from lib.state import State


# --- tier classification ---

def test_classify_reversal_high():
    assert classify("DRAM prices fall as oversupply builds") == ("HIGH", "C6_PRICE_REVERSAL")


def test_classify_price_cut_high():
    assert classify("Samsung cuts NAND prices amid weak demand") == ("HIGH", "C6_PRICE_REVERSAL")


def test_classify_surge_med():
    assert classify("HBM shortage drives record high memory prices") == ("MED", "C6_PRICE_SURGE")


def test_classify_order_unwind_critical():
    assert classify("Hyperscaler cancels DRAM orders as capex plans shift") == \
        ("CRITICAL", "C6_ORDER_UNWIND")


def test_classify_inventory_writedown_critical():
    assert classify("NAND maker takes inventory write-down") == ("CRITICAL", "C6_ORDER_UNWIND")


def test_critical_beats_high_when_both_present():
    text = "DRAM prices fall; Micron flags order cancellations"
    assert classify(text) == ("CRITICAL", "C6_ORDER_UNWIND")


# --- rejection paths ---

def test_no_subject_returns_none():
    assert classify("Oil prices fall on oversupply") is None


def test_no_tier_token_returns_none():
    assert classify("DRAM market sees steady demand in Q2") is None


def test_consumer_deal_noise_rejected():
    assert classify("SSD prices drop in Black Friday deals roundup") is None
    assert classify("Best SSD deals: prices fall ahead of Prime Day") is None


def test_proximity_window_kills_distant_pairing():
    """Subject and token hundreds of chars apart must not fire."""
    text = (
        "The DRAM industry held its annual conference. "
        + ("Lorem ipsum dolor sit amet. " * 30)
        + "Elsewhere, banana prices fall sharply."
    )
    assert classify(text) is None


def test_hdd_and_hard_drive_count_as_subject():
    assert classify("HDD prices surge on AI storage demand") == ("MED", "C6_PRICE_SURGE")
    assert classify("Hard drive shortage hits data centers") == ("MED", "C6_PRICE_SURGE")


def test_glut_near_subject_fires_high():
    assert classify("Analysts warn of NAND glut in 2027") == ("HIGH", "C6_PRICE_REVERSAL")


# --- run() integration ---

_FEED_BODY = """<?xml version="1.0"?><rss version="2.0"><channel>
<title>x</title><link>http://x</link><description>x</description>
<item><title>DRAM contract prices fall 10% as oversupply emerges</title>
<link>http://example.com/a</link>
<description>TrendForce reports DRAM prices dropped on inventory correction</description>
<guid>m1</guid><pubDate>Fri, 12 Jun 2026 00:00:00 GMT</pubDate>
</item>
<item><title>NAND shortage: prices surge to record high</title>
<link>http://example.com/b</link>
<description>NAND flash prices spiked on AI server demand</description>
<guid>m2</guid><pubDate>Fri, 12 Jun 2026 00:00:00 GMT</pubDate>
</item>
<item><title>Weather forecast sunny</title>
<link>http://example.com/c</link>
<description>No memory content here</description>
<guid>m3</guid><pubDate>Fri, 12 Jun 2026 00:00:00 GMT</pubDate>
</item>
</channel></rss>"""


@responses.activate
def test_run_returns_classified_alerts(tmp_path):
    feed_url = "http://example.com/feed.xml"
    responses.add(responses.GET, feed_url, body=_FEED_BODY, status=200)

    st = State("c6", db_path=tmp_path / "t.sqlite")
    cat = Catalyst6(state=st, feeds=[feed_url])
    alerts = cat.run()
    sevs = sorted(a.severity for a in alerts)
    assert sevs == ["HIGH", "MED"]
    assert all(a.catalyst == "C6" for a in alerts)
    assert any("[C6-HIGH]" in a.subject for a in alerts)


@responses.activate
def test_run_dedups_seen_entries(tmp_path):
    feed_url = "http://example.com/feed.xml"
    responses.add(responses.GET, feed_url, body=_FEED_BODY, status=200)
    responses.add(responses.GET, feed_url, body=_FEED_BODY, status=200)

    st = State("c6", db_path=tmp_path / "t.sqlite")
    cat = Catalyst6(state=st, feeds=[feed_url])
    first = cat.run()
    second = cat.run()
    assert len(first) == 2
    assert second == []


# --- retail and ticker-collision guards ------------------------------------
# Verbatim headlines from the alerts table: 30 of the 52 unique HIGH alerts
# ever raised were consumer SKU pricing, not the memory cycle.

def test_retail_sku_pricing_is_not_a_cycle_signal():
    for t in [
        "WD_Black SN8100 NVMe SSD drops to $699.99 in latest price cut",
        "Samsung 990 PRO SSD drops to $219.99 in new price cut",
        "Upgrade Your Storage With Samsung's 4TB 9100 PRO SSD, Now 41% Off On Amazon",
        "Save $521 on this RTX 5070 gaming PC, now just $1,349 - huge price drop",
    ]:
        assert classify(t) is None, t


def test_hbm_ticker_collision_is_not_memory():
    """HBM is also Hudbay Minerals (copper), and a Lafarge cement brand."""
    for t in [
        "Jefferies Maintains Hudbay Minerals(HBM.US) With Buy Rating, Cuts Target Price to $35.18",
        "RBC Capital Maintains Hudbay Minerals(HBM.US) With Buy Rating, Cuts Target Price to $28.17",
        "Umahi demands cut in cement prices as Lafarge rebrands to HBM",
    ]:
        assert classify(t) is None, t


def test_genuine_memory_price_reversal_still_high():
    for t in [
        "DRAM crisis: Analysts expect drastic price drop in 2028",
        "Semiconductor ETFs Attract $25 Billion Inflows as DRAM Prices Tumble 40%",
        "CoreWeave Weighs Derivatives Hedge Against Memory Chip Price Plunge, Sources Say",
        "MU Stock Heads Under $1,000 as Micron Selloff Deepens on DRAM Lawsuit, Oversupply Concerns",
    ]:
        assert (classify(t) or (None,))[0] == "HIGH", t

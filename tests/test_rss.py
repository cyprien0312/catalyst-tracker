from pathlib import Path
import responses
from lib.rss import fetch
from lib.state import State

FIX = Path(__file__).parent / "fixtures"
URL = "http://example.com/feed.xml"


@responses.activate
def test_fetch_returns_entries_first_time(tmp_path):
    body = (FIX / "sample_feed.xml").read_text()
    responses.add(responses.GET, URL, body=body, status=200, content_type="application/rss+xml")
    st = State("rss", db_path=tmp_path / "t.sqlite")
    entries = fetch(URL, st)
    assert len(entries) == 2
    titles = {e.title for e in entries}
    assert any("bond prospectus" in t for t in titles)


@responses.activate
def test_fetch_dedups_on_second_call(tmp_path):
    body = (FIX / "sample_feed.xml").read_text()
    responses.add(responses.GET, URL, body=body, status=200)
    responses.add(responses.GET, URL, body=body, status=200)
    st = State("rss", db_path=tmp_path / "t.sqlite")
    first = fetch(URL, st)
    second = fetch(URL, st)
    assert len(first) == 2 and second == []


@responses.activate
def test_fetch_handles_404_gracefully(tmp_path):
    responses.add(responses.GET, URL, status=404)
    st = State("rss", db_path=tmp_path / "t.sqlite")
    assert fetch(URL, st) == []


@responses.activate
def test_fetch_handles_304_not_modified(tmp_path):
    responses.add(responses.GET, URL, status=304)
    st = State("rss", db_path=tmp_path / "t.sqlite")
    assert fetch(URL, st) == []


@responses.activate
def test_rss_meta_table_populated_with_etag(tmp_path):
    body = (FIX / "sample_feed.xml").read_text()
    responses.add(
        responses.GET, URL, body=body, status=200,
        headers={"ETag": "\"abc123\"", "Last-Modified": "Wed, 21 Oct 2026 07:28:00 GMT"},
    )
    st = State("rss", db_path=tmp_path / "t.sqlite")
    fetch(URL, st)
    with st.connection() as c:
        row = c.execute(
            "SELECT etag, last_modified FROM rss_meta WHERE feed_url=?",
            (URL,),
        ).fetchone()
    assert row is not None
    assert row[0] == "\"abc123\""
    assert row[1] == "Wed, 21 Oct 2026 07:28:00 GMT"

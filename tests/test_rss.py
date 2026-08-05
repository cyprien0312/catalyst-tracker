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


# --- entry_text: publisher names and feed markup are not content -----------

from lib.rss import Entry, entry_text, strip_source_suffix  # noqa: E402


def _entry(title, summary=""):
    return Entry(feed_url="f", guid="g", title=title, link="l",
                 summary=summary, published="p")


def test_strip_source_suffix_removes_masthead():
    assert strip_source_suffix("DRAM prices tumble 40% - Reuters") == "DRAM prices tumble 40%"
    assert strip_source_suffix("Micron jumps 12% - parameter.io") == "Micron jumps 12%"


def test_strip_source_suffix_keeps_headline_prose():
    # A long tail with sentence punctuation is part of the headline, not a masthead.
    t = "Analysts split - some see a glut, others see structural demand through 2028."
    assert strip_source_suffix(t) == t


def test_entry_text_drops_publisher_name():
    """A publisher's name must not supply a tier token.

    Real C3 false positive: the accounting blog "Going Concern" put the phrase
    'going concern' into every one of its headlines.
    """
    e = _entry(
        "Friday Footnotes: OpenAI CFO Says Don't Sweat Token Costs - Going Concern",
        '<a href="https://news.google.com/rss/articles/CBMiXXXX">Friday Footnotes: '
        'OpenAI CFO Says Don\'t Sweat Token Costs</a>&nbsp;&nbsp;'
        '<font color="#6f6f6f">Going Concern</font>',
    )
    assert "going concern" not in entry_text(e).lower()


def test_entry_text_strips_markup_and_opaque_url():
    e = _entry("Headline - Src",
               '<a href="https://news.google.com/rss/articles/CBMiab0Ncd">Headline</a>')
    out = entry_text(e)
    assert "<" not in out and "https://" not in out
    assert "Headline" in out

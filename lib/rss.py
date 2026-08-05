"""RSS / Atom feed fetcher with per-feed dedup via SQLite state.

Designed for the catalyst tracker:
- Per-feed etag / last-modified persisted in dedicated `rss_meta` table.
- Per-entry GUID stored under table `rss_seen:{url}` in `seen`.
- Returns only new entries each call.
"""
from __future__ import annotations

import hashlib
import html
import re
import time
from dataclasses import dataclass
from typing import Iterable

import feedparser
import requests

from lib.log import get_logger
from lib.state import State

log = get_logger(__name__)


_RSS_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS rss_meta (
    feed_url     TEXT PRIMARY KEY,
    etag         TEXT,
    last_modified TEXT,
    ts           INTEGER NOT NULL
);
"""

_LEGACY_CLEANED = False


def _ensure_meta_table(state: State) -> None:
    """Create rss_meta if missing and cleanup legacy rss_meta_blob rows once per process."""
    global _LEGACY_CLEANED
    with state.connection() as c:
        c.executescript(_RSS_META_SCHEMA)
        if not _LEGACY_CLEANED:
            try:
                c.execute("DELETE FROM seen WHERE table_name='rss_meta_blob'")
            except Exception:
                pass
            _LEGACY_CLEANED = True


@dataclass(frozen=True)
class Entry:
    feed_url: str
    guid: str
    title: str
    link: str
    summary: str
    published: str


# --- text normalisation for the news classifiers (C3/C6/C11) ---------------
#
# A Google News RSS item is not plain text. The title ends with " - Publisher",
# and the summary is HTML wrapping an opaque base64 article URL plus the
# publisher name again:
#
#   <a href="https://news.google.com/rss/articles/CBMie0FVX3lxTE5k...">Headline</a>
#   &nbsp;&nbsp;<font color="#6f6f6f">AOL.com</font>
#
# Classifying that raw blob lets a *publisher's name* supply a tier token. Real
# case: "Friday Footnotes: OpenAI CFO Says Don't Sweat Token Costs ... - Going
# Concern" fired a C3 CRITICAL because the accounting blog is named "Going
# Concern". The article had nothing to do with OpenAI's solvency.

_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+")
# Google News marks the publisher with a grey <font> tag. Drop it wholesale —
# tag *and* content — before any other stripping.
_FONT_BLOCK_RE = re.compile(r"<font\b[^>]*>.*?</font>", re.I | re.S)

# " - Publisher" tail on the title.
_SOURCE_TAIL_RE = re.compile(r"\s+-\s+([^-]{1,40})$")


def _looks_like_masthead(tail: str) -> bool:
    """A publisher name is a short noun phrase or a bare domain."""
    if re.fullmatch(r"[\w.-]+\.[a-z]{2,}", tail, re.I):   # parameter.io, AOL.com
        return True
    if len(tail.split()) > 6:                             # too long to be a masthead
        return False
    return not any(c in tail for c in ".!?;")             # prose punctuation ⇒ headline


def strip_source_suffix(title: str) -> str:
    """Drop the trailing ' - Publisher' that Google News appends to titles."""
    m = _SOURCE_TAIL_RE.search(title)
    if not m or not _looks_like_masthead(m.group(1).strip()):
        return title
    return title[: m.start()].rstrip()


def entry_text(entry: "Entry") -> str:
    """Classification text for a feed entry: headline + de-HTMLed summary.

    Strips markup, the opaque article URL, and the publisher name, so only what
    a human would read as the story reaches the proximity classifiers.
    """
    summary = _FONT_BLOCK_RE.sub(" ", entry.summary)
    summary = _URL_RE.sub(" ", _TAG_RE.sub(" ", summary))
    summary = re.sub(r"\s+", " ", html.unescape(summary)).strip()
    return f"{strip_source_suffix(entry.title)}\n{strip_source_suffix(summary)}"


def _entry_guid(entry: dict) -> str:
    for k in ("id", "guid", "link"):
        v = entry.get(k)
        if v:
            return str(v)
    h = hashlib.sha256(
        ((entry.get("title") or "") + "|" + (entry.get("summary") or "")[:200]).encode()
    ).hexdigest()
    return f"hash:{h}"


def _load_meta(state: State, feed_url: str) -> tuple[str | None, str | None]:
    with state.connection() as c:
        row = c.execute(
            "SELECT etag, last_modified FROM rss_meta WHERE feed_url=?",
            (feed_url,),
        ).fetchone()
    if not row:
        return None, None
    return row[0], row[1]


def _save_meta(state: State, feed_url: str, etag: str | None, last_modified: str | None) -> None:
    with state.connection() as c:
        c.execute(
            "INSERT INTO rss_meta(feed_url, etag, last_modified, ts) VALUES(?,?,?,?) "
            "ON CONFLICT(feed_url) DO UPDATE SET etag=excluded.etag, "
            "last_modified=excluded.last_modified, ts=excluded.ts",
            (feed_url, etag, last_modified, int(time.time())),
        )


def fetch(feed_url: str, state: State, *, timeout: int = 30,
          user_agent: str = "catalyst-tracker") -> list[Entry]:
    """Fetch a feed and return entries we haven't seen before."""
    _ensure_meta_table(state)
    headers = {"User-Agent": user_agent}
    etag, lm = _load_meta(state, feed_url)
    if etag:
        headers["If-None-Match"] = etag
    if lm:
        headers["If-Modified-Since"] = lm

    try:
        resp = requests.get(feed_url, headers=headers, timeout=timeout)
    except requests.RequestException:
        log.exception("rss fetch failed %s", feed_url)
        return []

    if resp.status_code == 304:
        return []
    if resp.status_code >= 400:
        log.warning("rss %s returned %s", feed_url, resp.status_code)
        return []

    new_etag = resp.headers.get("ETag")
    new_lm = resp.headers.get("Last-Modified")
    if new_etag or new_lm:
        _save_meta(state, feed_url, new_etag, new_lm)

    parsed = feedparser.parse(resp.content)
    out: list[Entry] = []
    table = f"rss_seen:{feed_url}"
    for entry in parsed.entries:
        guid = _entry_guid(entry)
        if state.seen(table, guid, ttl_seconds=30 * 86400):
            continue
        state.mark_seen(table, guid)
        out.append(Entry(
            feed_url=feed_url,
            guid=guid,
            title=entry.get("title", "") or "",
            link=entry.get("link", "") or "",
            summary=entry.get("summary", "") or "",
            published=entry.get("published", "") or "",
        ))
    return out


def fetch_many(feed_urls: Iterable[str], state: State) -> list[Entry]:
    out: list[Entry] = []
    for url in feed_urls:
        out.extend(fetch(url, state))
    return out

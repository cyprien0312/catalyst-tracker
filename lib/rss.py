"""RSS / Atom feed fetcher with per-feed dedup via SQLite state.

Designed for the catalyst tracker:
- Per-feed etag / last-modified persisted in dedicated `rss_meta` table.
- Per-entry GUID stored under table `rss_seen:{url}` in `seen`.
- Returns only new entries each call.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Iterable

import feedparser
import requests

from lib.state import State


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
    except requests.RequestException as e:
        print(f"rss: fetch failed {feed_url}: {e}")
        return []

    if resp.status_code == 304:
        return []
    if resp.status_code >= 400:
        print(f"rss: {feed_url} returned {resp.status_code}")
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

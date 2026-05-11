"""RSS / Atom feed fetcher with per-feed dedup via SQLite state.

Designed for the catalyst tracker:
- Per-feed etag / last-modified persisted in `seen` under key `rss_meta:{url}`.
- Per-entry GUID stored under table `rss_seen:{url}`.
- Returns only new entries each call.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Iterable

import feedparser
import requests

from lib.state import State


@dataclass(frozen=True)
class Entry:
    feed_url: str
    guid: str
    title: str
    link: str
    summary: str
    published: str


def _entry_guid(entry: dict) -> str:
    # feedparser gives us .id, .guid, .link — pick best, else hash title+summary.
    for k in ("id", "guid", "link"):
        v = entry.get(k)
        if v:
            return str(v)
    h = hashlib.sha256(
        ((entry.get("title") or "") + "|" + (entry.get("summary") or "")[:200]).encode()
    ).hexdigest()
    return f"hash:{h}"


def fetch(feed_url: str, state: State, *, timeout: int = 30,
          user_agent: str = "catalyst-tracker") -> list[Entry]:
    """Fetch a feed and return entries we haven't seen before."""
    meta_key = f"rss_meta:{feed_url}"
    headers = {"User-Agent": user_agent}
    # Read prior etag/last-modified.
    with state.connection() as c:
        row = c.execute(
            "SELECT key FROM seen WHERE table_name='rss_meta_blob' AND key LIKE ?",
            (meta_key + ":%",),
        ).fetchone()
    if row:
        try:
            blob = json.loads(row[0].split(":", 2)[2])
            if blob.get("etag"):
                headers["If-None-Match"] = blob["etag"]
            if blob.get("last_modified"):
                headers["If-Modified-Since"] = blob["last_modified"]
        except Exception:
            pass

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

    # Persist new etag / last-modified.
    etag = resp.headers.get("ETag")
    lm = resp.headers.get("Last-Modified")
    if etag or lm:
        blob = json.dumps({"etag": etag, "last_modified": lm})
        with state.connection() as c:
            c.execute("DELETE FROM seen WHERE table_name='rss_meta_blob' AND key LIKE ?",
                      (meta_key + ":%",))
            c.execute(
                "INSERT INTO seen(table_name, key, ts) VALUES(?,?,?)",
                ("rss_meta_blob", f"{meta_key}:_:{blob}", int(time.time())),
            )

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

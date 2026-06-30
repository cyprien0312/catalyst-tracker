"""Tests for the fetch+verify knowledge flow (lib/knowledge_fetch.py).

All fetchers are stubbed — no network. Covers the verify gate (band + empty +
NaN), reading construction, and the publish path into a tmp corpus dir.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import knowledge, knowledge_fetch as kf


# --------------------------------------------------------------------------- #
# verify gate
# --------------------------------------------------------------------------- #
def test_ok_band():
    assert kf._ok(2.83, 1.0, 25.0)
    assert not kf._ok(0.5, 1.0, 25.0)        # below band
    assert not kf._ok(99.0, 1.0, 25.0)       # above band
    assert not kf._ok(float("nan"), 1.0, 25.0)
    assert not kf._ok(float("inf"), 1.0, 25.0)
    assert not kf._ok("2.83", 1.0, 25.0)     # not a number


def test_yoy_latest():
    monthly = [(f"2025-{m:02d}-01", 100.0 + m) for m in range(1, 13)]
    monthly += [("2026-01-01", 112.0)]  # 13 points: 112 vs 101 a year earlier
    date, yoy = kf._yoy_latest(monthly)
    assert date == "2026-01-01"
    assert yoy == pytest.approx((112.0 / 101.0 - 1) * 100)

    assert kf._yoy_latest([("2025-01-01", 100.0)]) is None  # too short


# --------------------------------------------------------------------------- #
# probes
# --------------------------------------------------------------------------- #
def test_hy_oas_reading():
    r = kf.hy_oas(fetch=lambda _id: [("2026-06-26", 2.80), ("2026-06-27", 2.83)])
    assert r is not None
    assert r.slug == "live-hy-oas"
    assert "2.83" in r.topic and "2026-06-27" in r.topic
    assert r.source == "https://fred.stlouisfed.org/series/BAMLH0A0HYM2"
    assert "c7" in r.tags and "live" in r.tags


def test_probe_rejects_empty_and_out_of_band():
    assert kf.hy_oas(fetch=lambda _id: []) is None             # empty series
    assert kf.hy_oas(fetch=lambda _id: [("d", 999.0)]) is None  # out of band


def test_cpi_yoy_reading():
    monthly = [(f"2025-{m:02d}-01", 300.0) for m in range(1, 13)]
    monthly += [("2026-01-01", 312.0)]  # +4.0% YoY
    r = kf.cpi_yoy(fetch=lambda _id: monthly)
    assert r is not None and r.slug == "live-cpi-yoy"
    assert "4.0%" in r.topic and "c8" in r.tags


def test_btc_mayer_reading():
    closes = [(i, 100.0) for i in range(199)] + [(199, 240.0)]  # 200 pts, last=240
    r = kf.btc_mayer(fetch=lambda _days: closes)
    assert r is not None and r.slug == "live-btc-mayer"
    # sma200 = (199*100 + 240)/200 = 100.7 ; mayer ~= 2.38
    assert "2.38" in r.topic
    assert kf.btc_mayer(fetch=lambda _days: closes[:50]) is None  # < 200 pts


def test_ndx_reading():
    series = [("2026-06-01", 30000.0), ("2026-06-29", 29100.0)]  # -3.0%
    r = kf.ndx_reading(fetch=lambda _id: series)
    assert r is not None and r.slug == "live-ndx-drawdown"
    assert "-3.0%" in r.topic and "u100" in r.tags


def test_henry_hub_reading():
    assert kf.henry_hub(fetch=lambda: []) is None  # no EIA key -> []
    r = kf.henry_hub(fetch=lambda: [3.0, 4.0, 5.0])
    assert r is not None and "4.00" in r.topic and "c5" in r.tags


# --------------------------------------------------------------------------- #
# gather + publish
# --------------------------------------------------------------------------- #
def test_gather_skips_failing_probe():
    def good():
        return kf.Reading("s", "t", "c", "q", "https://x", ["ai-infra"])

    def boom():
        raise RuntimeError("network")

    def empty():
        return None

    assert len(kf.gather([good, boom, empty])) == 1


def test_publish_writes_and_is_idempotent(tmp_path: Path):
    (tmp_path / "ai-infra").mkdir()
    reading = kf.Reading(
        slug="live-hy-oas", topic="HY OAS = 2.83 pp", claim="HY OAS is 2.83",
        quote="BAMLH0A0HYM2: 2.83", source="https://fred.stlouisfed.org/series/BAMLH0A0HYM2",
        tags=["ai-infra", "live", "c7"],
    )
    w1, s1 = kf.publish([reading], base_dir=tmp_path, last_verified="2026-06-30")
    assert (w1, s1) == (1, 0)
    # re-publish the same source -> overwrite in place, no duplicate file
    updated = kf.Reading(**{**reading.__dict__, "topic": "HY OAS = 3.10 pp"})
    kf.publish([updated], base_dir=tmp_path, last_verified="2026-07-01")
    facts = knowledge.load_facts(base_dir=tmp_path)
    assert len(facts) == 1
    assert facts[0].topic == "HY OAS = 3.10 pp"
    assert facts[0].tags == ("ai-infra", "live", "c7")

"""Fetch + verify: pull live external readings into the shared knowledge corpus.

The companion to ``scripts/sync_knowledge.py`` (which publishes the tracker's static
*threshold* facts). This module pulls the **live numeric readings** behind those
thresholds — HY/IG credit spreads, CPI / core-PCE, the broad USD index, the 10y real
yield, BTC's Mayer Multiple, the Nasdaq-100 drawdown, the Henry Hub strip — from the
same keyless sources the catalysts already use (FRED CSV, CoinGecko, EIA), and writes
each as a sourced, dated fact into the ``ai-infra`` domain.

"Verify" is a two-part gate, so we never poison the corpus with a bad datum:
1. the value comes from an authoritative source (FRED / CoinGecko / EIA), and
2. it is finite and inside a hand-set plausibility band for that series.

A probe that fails either gate (network down, empty series, NaN, out-of-band) yields
``None`` and is simply **not written** — the previous good reading stays in place.
Every probe degrades to ``None`` rather than raising, matching the rest of the tracker.

    .venv/bin/python -m scripts.fetch_knowledge --dry-run   # fetch + verify, write nothing
    .venv/bin/python -m scripts.fetch_knowledge             # refresh ai-infra readings
"""
from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from pathlib import Path

from lib import knowledge
from lib.crypto import btc_daily_closes
from lib.eia import henry_hub_strip
from lib.fred import series_csv
from lib.index_quote import ndx_drawdown
from lib.knowledge import FactClaim
from lib.log import get_logger

_log = get_logger(__name__)

_FRED_SERIES = "https://fred.stlouisfed.org/series/{id}"
_COINGECKO_BTC = "https://www.coingecko.com/en/coins/bitcoin"
_EIA_NG = "https://www.eia.gov/dnav/ng/hist/rngc1d.htm"


@dataclass(frozen=True)
class Reading:
    """One verified live datum, ready to write as a knowledge note."""
    slug: str
    topic: str
    claim: str
    quote: str
    source: str
    tags: list[str]


def _ok(value: object, lo: float, hi: float) -> bool:
    """Verify gate: a real, finite number inside the plausibility band."""
    return isinstance(value, (int, float)) and math.isfinite(value) and lo <= value <= hi


def _yoy_latest(monthly: list[tuple[str, float]]) -> tuple[str, float] | None:
    """Latest (date, YoY%) using the value 12 observations earlier (matches C8)."""
    if len(monthly) < 13:
        return None
    date_i, val_i = monthly[-1]
    _, val_prior = monthly[-13]
    if not val_prior:
        return None
    return date_i, (val_i / val_prior - 1.0) * 100.0


# --------------------------------------------------------------------------- #
# probes — each returns a verified Reading, or None
# --------------------------------------------------------------------------- #
def _fred_level_probe(
    *, fred_id: str, label: str, slug: str, unit: str, lo: float, hi: float,
    tag: str, trigger: str, fetch,
) -> Reading | None:
    series = fetch(fred_id)
    if not series:
        return None
    date, value = series[-1]
    if not _ok(value, lo, hi):
        _log.info("fetch.reject id=%s value=%r band=[%s,%s]", fred_id, value, lo, hi)
        return None
    return Reading(
        slug=slug,
        topic=f"{label} = {value:.2f}{unit} (as of {date})",
        claim=f"{label} latest reading is {value:.2f}{unit} as of {date}. {trigger}",
        quote=f"{fred_id} ({label}), {date}: {value:.2f}",
        source=_FRED_SERIES.format(id=fred_id),
        tags=["ai-infra", "live", tag],
    )


def hy_oas(fetch=series_csv) -> Reading | None:
    return _fred_level_probe(
        fred_id="BAMLH0A0HYM2", label="ICE BofA US High-Yield OAS", slug="live-hy-oas",
        unit=" pp", lo=1.0, hi=25.0, tag="c7",
        trigger="C7 fires at +75bp off the trailing-90 low, or >=400bp absolute.",
        fetch=fetch,
    )


def ig_oas(fetch=series_csv) -> Reading | None:
    return _fred_level_probe(
        fred_id="BAMLC0A0CM", label="ICE BofA US Investment-Grade OAS", slug="live-ig-oas",
        unit=" pp", lo=0.3, hi=10.0, tag="c7",
        trigger="C7 fires at +30bp off the trailing-90 low, or >=125bp absolute.",
        fetch=fetch,
    )


def broad_usd(fetch=series_csv) -> Reading | None:
    return _fred_level_probe(
        fred_id="DTWEXBGS", label="Nominal Broad US Dollar Index", slug="live-broad-usd",
        unit="", lo=90.0, hi=160.0, tag="c10",
        trigger="C10 fires at +2.5% above the trailing-90 low.",
        fetch=fetch,
    )


def real_yield_10y(fetch=series_csv) -> Reading | None:
    return _fred_level_probe(
        fred_id="DFII10", label="10-Year Treasury real (TIPS) yield", slug="live-10y-real-yield",
        unit=" pp", lo=-3.0, hi=5.0, tag="c10",
        trigger="C10 fires at +40bp above the trailing-90 low, or at the restrictive absolute level.",
        fetch=fetch,
    )


def cpi_yoy(fetch=series_csv) -> Reading | None:
    latest = _yoy_latest(fetch("CPIAUCSL"))
    if latest is None:
        return None
    date, value = latest
    if not _ok(value, -5.0, 20.0):
        _log.info("fetch.reject id=CPI_YOY value=%r", value)
        return None
    return Reading(
        slug="live-cpi-yoy",
        topic=f"US CPI inflation = {value:.1f}% YoY (as of {date})",
        claim=f"US headline CPI is {value:.1f}% YoY as of {date}. "
              f"C8 fires at >=3.5%, or after two consecutive monthly rises while >=3.0%.",
        quote=f"CPIAUCSL (CPI-U), {date}: {value:.1f}% YoY",
        source=_FRED_SERIES.format(id="CPIAUCSL"),
        tags=["ai-infra", "live", "c8"],
    )


def core_pce_yoy(fetch=series_csv) -> Reading | None:
    latest = _yoy_latest(fetch("PCEPILFE"))
    if latest is None:
        return None
    date, value = latest
    if not _ok(value, -2.0, 15.0):
        _log.info("fetch.reject id=PCE_YOY value=%r", value)
        return None
    return Reading(
        slug="live-core-pce-yoy",
        topic=f"US core PCE inflation = {value:.1f}% YoY (as of {date})",
        claim=f"US core PCE (the Fed's target metric) is {value:.1f}% YoY as of {date}. "
              f"C8 treats >=3.0% as 'Fed can't cut' territory.",
        quote=f"PCEPILFE (core PCE), {date}: {value:.1f}% YoY",
        source=_FRED_SERIES.format(id="PCEPILFE"),
        tags=["ai-infra", "live", "c8"],
    )


def btc_mayer(fetch=btc_daily_closes) -> Reading | None:
    pts = fetch(365)
    closes = [p for _, p in pts]
    if len(closes) < 200:
        return None
    price = closes[-1]
    window = closes[-200:]
    sma200 = sum(window) / len(window)
    if sma200 <= 0:
        return None
    mayer = price / sma200
    if not _ok(mayer, 0.2, 5.0):
        _log.info("fetch.reject id=BTC_MAYER value=%r", mayer)
        return None
    date = _dt.datetime.utcfromtimestamp(pts[-1][0] / 1000).date().isoformat()
    return Reading(
        slug="live-btc-mayer",
        topic=f"BTC Mayer Multiple = {mayer:.2f} (price/200DMA, as of {date})",
        claim=f"Bitcoin's Mayer Multiple (price / 200-day SMA) is {mayer:.2f} as of {date}. "
              f"C9 flags froth at >=2.4 (HIGH at >=2.8).",
        quote=f"Bitcoin ${price:,.0f}, 200DMA ${sma200:,.0f}, Mayer {mayer:.2f} (CoinGecko, {date})",
        source=_COINGECKO_BTC,
        tags=["ai-infra", "live", "c9"],
    )


def ndx_reading(fetch=None) -> Reading | None:
    data = ndx_drawdown(fetch) if fetch is not None else ndx_drawdown()
    if not data:
        return None
    dd = data["drawdown"]
    if not _ok(dd, -0.95, 0.05):
        _log.info("fetch.reject id=NDX_DD value=%r", dd)
        return None
    return Reading(
        slug="live-ndx-drawdown",
        topic=f"Nasdaq-100 drawdown from ATH = {dd*100:.1f}% (as of {data['date']})",
        claim=f"Nasdaq-100 is {data['current']:,.0f}, {dd*100:.1f}% below its "
              f"{data['ath']:,.0f} all-time high ({data['ath_date']}) as of {data['date']}. "
              f"Drives the U100/NDX buy-plan ladder.",
        quote=f"NASDAQ100, {data['date']}: {data['current']:,.0f} "
              f"(ATH {data['ath']:,.0f} on {data['ath_date']}, drawdown {dd*100:.1f}%)",
        source=_FRED_SERIES.format(id="NASDAQ100"),
        tags=["ai-infra", "live", "u100"],
    )


def henry_hub(fetch=henry_hub_strip) -> Reading | None:
    strip = fetch()
    if not strip:
        return None
    avg = sum(strip) / len(strip)
    if not _ok(avg, 1.0, 20.0):
        _log.info("fetch.reject id=HENRY_HUB value=%r", avg)
        return None
    return Reading(
        slug="live-henry-hub-strip",
        topic=f"Henry Hub 12-month gas strip avg = ${avg:.2f}/MMBtu",
        claim=f"The Henry Hub front-month+12 futures strip averages ${avg:.2f}/MMBtu. "
              f"C5 fires when this 12-month strip average is >=$5.00.",
        quote=f"EIA Henry Hub strip ({len(strip)} contracts), avg ${avg:.2f}/MMBtu",
        source=_EIA_NG,
        tags=["ai-infra", "live", "c5"],
    )


PROBES = [
    hy_oas, ig_oas, broad_usd, real_yield_10y,
    cpi_yoy, core_pce_yoy, btc_mayer, ndx_reading, henry_hub,
]


def gather(probes=PROBES) -> list[Reading]:
    """Run every probe; collect the ones that fetched + verified. Never raises."""
    out: list[Reading] = []
    for probe in probes:
        try:
            reading = probe()
        except Exception:  # a single bad probe must not sink the batch
            _log.exception("fetch.probe_failed probe=%s", getattr(probe, "__name__", probe))
            reading = None
        if reading is not None:
            out.append(reading)
    return out


def publish(
    readings: list[Reading],
    *,
    dom: str | None = None,
    base_dir: Path | None = None,
    last_verified: str | None = None,
) -> tuple[int, int]:
    """Write verified readings to the corpus. Returns ``(written, skipped)``."""
    written = skipped = 0
    for r in readings:
        path = knowledge.write_fact(
            slug=r.slug,
            topic=r.topic,
            claims=[FactClaim(claim=r.claim, src=r.source, quote=r.quote)],
            tags=r.tags,
            dom=dom,
            base_dir=base_dir,
            last_verified=last_verified,
        )
        if path is None:
            skipped += 1
        else:
            written += 1
    return written, skipped

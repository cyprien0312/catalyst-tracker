"""Catalyst 9 — Crypto Cycle Top.

Bitcoin doesn't respond to the equity/credit valuation tools the other
catalysts use, but it runs on the same fuel: cheap money and risk appetite.
The research lists a set of on-chain/technical cycle-top indicators; the two
that are computable from daily price alone — and that have the best historical
timing records — are implemented here:

- Mayer Multiple = price / 200-day SMA. > 2.4 is historically a froth zone.
- Pi Cycle Top = the 111-day SMA crossing ABOVE 2× the 350-day SMA. This cross
  has called the last several cycle tops to within days.

Source: CoinGecko public API (keyless), daily closes.

Signals:
- MAYER_HOT      — Mayer Multiple ≥ 2.4 (MED), ≥ 2.8 (HIGH).
- PI_CYCLE_TOP   — 111 SMA crosses up through 2× 350 SMA today (HIGH).
"""
from __future__ import annotations

from catalysts.base import Alert, CatalystBase
from lib.crypto import btc_daily_closes
from lib.explanations import append_context
from lib.log import get_logger
from lib.state import State

log = get_logger(__name__)

MAYER_HOT = 2.4
MAYER_HIGH = 2.8


def _sma(values: list[float], window: int, offset: int = 0) -> float | None:
    """Simple moving average of `window` values ending `offset` from the end.

    offset=0 → most recent window; offset=1 → the window ending yesterday.
    """
    end = len(values) - offset
    start = end - window
    if start < 0 or end <= 0:
        return None
    seg = values[start:end]
    return sum(seg) / len(seg)


def evaluate(closes: list[float]) -> list[dict]:
    """Pure signal logic over ascending daily closes (latest last)."""
    out: list[dict] = []
    if len(closes) < 200:
        return out
    price = closes[-1]

    sma200 = _sma(closes, 200)
    if sma200:
        mayer = price / sma200
        if mayer >= MAYER_HOT:
            sev = "HIGH" if mayer >= MAYER_HIGH else "MED"
            out.append({"kind": "MAYER_HOT", "severity": sev,
                        "mayer": mayer, "price": price, "sma200": sma200})

    # Pi Cycle Top: need today's and yesterday's 111 and 350 SMAs.
    sma111 = _sma(closes, 111)
    sma350 = _sma(closes, 350)
    sma111_y = _sma(closes, 111, offset=1)
    sma350_y = _sma(closes, 350, offset=1)
    if None not in (sma111, sma350, sma111_y, sma350_y):
        crossed_up = sma111_y < 2 * sma350_y and sma111 >= 2 * sma350
        if crossed_up:
            out.append({"kind": "PI_CYCLE_TOP", "severity": "HIGH",
                        "sma111": sma111, "sma350x2": 2 * sma350, "price": price})
    return out


def _ensure_table(state: State) -> None:
    with state.connection() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS c9_crypto (
                metric TEXT,
                obs_date TEXT,
                value REAL,
                PRIMARY KEY(metric, obs_date)
            )
        """)


def _store(state: State, metric: str, obs_date: str, value: float) -> None:
    with state.connection() as c:
        c.execute(
            "INSERT INTO c9_crypto(metric, obs_date, value) VALUES(?,?,?) "
            "ON CONFLICT(metric, obs_date) DO UPDATE SET value=excluded.value",
            (metric, obs_date, value),
        )


class Catalyst9(CatalystBase):
    name = "Crypto Cycle Top"

    def __init__(self, state: State | None = None, fetch=btc_daily_closes):
        self._state = state or State("c9")
        self._fetch = fetch
        _ensure_table(self._state)

    def run(self) -> list[Alert]:
        import datetime as _dt
        alerts: list[Alert] = []
        try:
            series = self._fetch()
        except Exception as e:
            log.warning("c9.coingecko fetch failed: %s", e)
            return alerts
        if not series or len(series) < 200:
            return alerts

        closes = [p for _, p in series]
        obs_date = _dt.date.fromtimestamp(series[-1][0] / 1000).isoformat()

        sma200 = _sma(closes, 200)
        if sma200:
            _store(self._state, "MAYER", obs_date, round(closes[-1] / sma200, 3))

        for sig in evaluate(closes):
            dedup = f"c9_{sig['kind']}|{obs_date}"
            if self._state.seen("c9_signals", dedup):
                continue
            self._state.mark_seen("c9_signals", dedup)
            if sig["kind"] == "MAYER_HOT":
                subject = f"[C9-{sig['severity']}] BTC Mayer Multiple {sig['mayer']:.2f} (≥ {MAYER_HOT})"
                body = (
                    f"Metric:   Mayer Multiple (price / 200DMA)\nDate:     {obs_date}\n"
                    f"Price:    ${sig['price']:,.0f}\n200DMA:   ${sig['sma200']:,.0f}\n"
                    f"Mayer:    {sig['mayer']:.2f}\n"
                )
                numbers = {"mayer": round(sig["mayer"], 2),
                           "price": round(sig["price"], 0),
                           "sma200": round(sig["sma200"], 0), "date": obs_date}
            else:  # PI_CYCLE_TOP
                subject = f"[C9-HIGH] BTC Pi Cycle Top triggered ({obs_date})"
                body = (
                    f"Metric:   Pi Cycle Top (111DMA crossed above 2×350DMA)\nDate:     {obs_date}\n"
                    f"Price:    ${sig['price']:,.0f}\n111DMA:   ${sig['sma111']:,.0f}\n"
                    f"2×350DMA: ${sig['sma350x2']:,.0f}\n"
                )
                numbers = {"sma111": round(sig["sma111"], 0),
                           "sma350x2": round(sig["sma350x2"], 0),
                           "price": round(sig["price"], 0), "date": obs_date}
            alerts.append(Alert(
                catalyst="C9", severity=sig["severity"], subject=subject,
                body=append_context(body, "C9", sig["kind"], numbers=numbers),
            ))
        return alerts


def _main(argv: list[str] | None = None) -> int:
    from catalysts.base import run_cli
    return run_cli(lambda args: Catalyst9(),
                   description="Catalyst 9: Crypto cycle top", argv=argv)


if __name__ == "__main__":
    raise SystemExit(_main())

"""Catalyst 10 — Liquidity Tightening (US dollar / real yields).

The transmission channel that actually pops leveraged bubbles isn't the
headline policy rate — it's the *price of money* moving against risk assets:
a surging broad dollar drains global liquidity, and rising real (inflation-
adjusted) yields raise the discount rate on every long-duration AI bet at once.
Both can tighten financial conditions even when the Fed holds — which is exactly
the "expectation management" mechanism market commentary keeps describing
(the Fed jawbones, conditions tighten, no hike required).

This catalyst is the cross-asset complement to C7 (credit) and C8 (inflation):
C7 watches the debt market repricing risk, C8 watches whether cheap money gets
taken away by inflation, and C10 watches the dollar/real-yield channel through
which that tightening is actually transmitted.

Sources (FRED keyless CSV):
- DTWEXBGS — Nominal Broad U.S. Dollar Index (daily).
- DFII10   — 10-Year Treasury Inflation-Indexed (real) yield (daily, %).

Signals (transition, computed in-memory from the fetched series):
- DOLLAR_SURGE      — broad USD ≥ trigger % above its trailing-90-session low.
                      Global liquidity squeeze. MED, HIGH at 2× the trigger.
- REAL_YIELD_SPIKE  — 10y real yield ≥ trigger pp above its trailing-90 low.
                      Discount-rate shock to long-duration assets. MED, HIGH at 2×.
- REAL_YIELD_STRESS — 10y real yield at/above an absolute restrictive level. HIGH.
"""
from __future__ import annotations

from catalysts.base import Alert, CatalystBase
from lib.explanations import append_context
from lib.fred import series_csv
from lib.log import get_logger
from lib.state import State

log = get_logger(__name__)

# Trailing window (sessions) used to establish the "low" the metric rises off.
LOOKBACK = 90

# Per-series config:
#   mode  — "pct" computes rise as % above the trailing low (dollar index);
#           "level" computes rise as the absolute difference (yields, in pp).
#   rise_trigger  — fires at/above this; severity escalates to HIGH at 2×.
#   stress_level  — optional absolute level that fires HIGH on its own.
SERIES = {
    "USD": {
        "fred_id": "DTWEXBGS",
        "label": "Broad USD Index",
        "mode": "pct",
        "rise_trigger": 2.5,        # +2.5% off the trailing low
        "rise_kind": "DOLLAR_SURGE",
        "stress_level": None,
        "stress_kind": None,
        "unit": "idx",
    },
    "REAL10": {
        "fred_id": "DFII10",
        "label": "10y Real Yield",
        "mode": "level",
        "rise_trigger": 0.40,       # +40 bp off the trailing low
        "rise_kind": "REAL_YIELD_SPIKE",
        "stress_level": 2.50,       # ≥ 2.50% real — restrictive
        "stress_kind": "REAL_YIELD_STRESS",
        "unit": "pct",
    },
}


def evaluate_series(values: list[float], cfg: dict) -> list[dict]:
    """Pure signal logic over an ascending list of values (latest last).

    Returns a list of {kind, severity, current, ...} signal dicts.
    """
    out: list[dict] = []
    if len(values) < 2:
        return out
    current = values[-1]
    window = values[-LOOKBACK:] if len(values) >= LOOKBACK else values
    low = min(window)
    if cfg["mode"] == "pct":
        rise = (current / low - 1.0) * 100.0 if low else 0.0
    else:
        rise = current - low

    if rise >= cfg["rise_trigger"]:
        sev = "HIGH" if rise >= 2 * cfg["rise_trigger"] else "MED"
        out.append({
            "kind": cfg["rise_kind"], "severity": sev,
            "current": current, "low": low, "rise": rise,
        })

    if cfg.get("stress_level") is not None and current >= cfg["stress_level"]:
        out.append({
            "kind": cfg["stress_kind"], "severity": "HIGH",
            "current": current, "stress_level": cfg["stress_level"],
        })
    return out


def _ensure_table(state: State) -> None:
    with state.connection() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS c10_liquidity (
                series TEXT,
                obs_date TEXT,
                value REAL,
                PRIMARY KEY(series, obs_date)
            )
        """)


def _store(state: State, series: str, obs_date: str, value: float) -> None:
    with state.connection() as c:
        c.execute(
            "INSERT INTO c10_liquidity(series, obs_date, value) VALUES(?,?,?) "
            "ON CONFLICT(series, obs_date) DO UPDATE SET value=excluded.value",
            (series, obs_date, value),
        )


def _fmt(value: float, unit: str) -> str:
    return f"{value:.2f}%" if unit == "pct" else f"{value:.1f}"


class Catalyst10(CatalystBase):
    name = "Liquidity Tightening"

    def __init__(self, state: State | None = None, fetch=series_csv):
        self._state = state or State("c10")
        self._fetch = fetch
        _ensure_table(self._state)

    def _check_series(self, key: str, cfg: dict) -> list[Alert]:
        alerts: list[Alert] = []
        series = self._fetch(cfg["fred_id"])
        if not series:
            return alerts
        obs_date = series[-1][0]
        values = [v for _, v in series]
        _store(self._state, key, obs_date, values[-1])

        unit = cfg["unit"]
        for sig in evaluate_series(values, cfg):
            dedup = f"c10_{sig['kind']}|{key}|{obs_date}"
            if self._state.seen("c10_signals", dedup):
                continue
            self._state.mark_seen("c10_signals", dedup)
            cur = _fmt(sig["current"], unit)
            if sig["kind"] == cfg["rise_kind"]:
                if cfg["mode"] == "pct":
                    move = f"+{sig['rise']:.1f}% off 90d-low"
                    trig = f"+{cfg['rise_trigger']:.1f}%"
                else:
                    move = f"+{sig['rise']*100:.0f}bp off 90d-low"
                    trig = f"+{cfg['rise_trigger']*100:.0f}bp"
                subject = f"[C10-{sig['severity']}] {cfg['label']} rising: {cur} ({move})"
                body = (
                    f"Series:   {key} ({cfg['fred_id']})\n"
                    f"Date:     {obs_date}\n"
                    f"Current:  {cur}\n"
                    f"90d low:  {_fmt(sig['low'], unit)}\n"
                    f"Move:     {move} (fire ≥ {trig})\n"
                )
                numbers = {"series": key, "current": round(sig["current"], 3),
                           "low": round(sig["low"], 3), "rise": round(sig["rise"], 3),
                           "obs_date": obs_date}
            else:  # *_STRESS (absolute level)
                stress = _fmt(sig["stress_level"], unit)
                subject = f"[C10-{sig['severity']}] {cfg['label']} restrictive: {cur} ≥ {stress}"
                body = (
                    f"Series:   {key} ({cfg['fred_id']})\n"
                    f"Date:     {obs_date}\n"
                    f"Current:  {cur}\n"
                    f"Stress ≥: {stress}\n"
                )
                numbers = {"series": key, "current": round(sig["current"], 3),
                           "stress_level": cfg["stress_level"], "obs_date": obs_date}
            alerts.append(Alert(
                catalyst="C10", severity=sig["severity"], subject=subject,
                body=append_context(body, "C10", sig["kind"], numbers=numbers),
            ))
        return alerts

    def run(self) -> list[Alert]:
        alerts: list[Alert] = []
        for key, cfg in SERIES.items():
            try:
                alerts.extend(self._check_series(key, cfg))
            except Exception as e:
                log.warning("c10.%s path failed: %s", key, e)
        return alerts


def _main(argv: list[str] | None = None) -> int:
    from catalysts.base import run_cli
    return run_cli(lambda args: Catalyst10(),
                   description="Catalyst 10: Liquidity tightening", argv=argv)


if __name__ == "__main__":
    raise SystemExit(_main())

"""Catalyst 7 — Credit Market Stress.

The research consensus (mid-2026) is that the AI buildout has shifted from an
*equity* story to a *debt* story, and that bubbles tear open in the credit
market before equities. Corporate credit spreads are at their tightest since
1997 — meaning the market is pricing almost no risk. The signal is therefore
NOT the tight level itself but spreads *starting to widen*. This is the
"fuse of fuses".

Sources (FRED keyless CSV):
- BAMLH0A0HYM2 — ICE BofA US High Yield Index Option-Adjusted Spread
- BAMLC0A0CM   — ICE BofA US Corporate (investment-grade) Index OAS

Signals (transition, computed in-memory from the fetched series):
- SPREAD_WIDENING — current OAS minus its trailing-90-session low ≥ trigger.
  The fuse is lighting. MED, escalates to HIGH at 2× the trigger.
- SPREAD_STRESS — current OAS ≥ an absolute stress level. Outright distress
  pricing. HIGH.
"""
from __future__ import annotations

from catalysts.base import Alert, CatalystBase
from lib.explanations import append_context
from lib.fred import series_csv
from lib.log import get_logger
from lib.state import State

log = get_logger(__name__)

# Trailing window (sessions) used to establish the "low" the spread widens off.
LOOKBACK = 90

# Per-series config: (FRED id, label, widening trigger pp, absolute stress pp).
SERIES = {
    "HY": {
        "fred_id": "BAMLH0A0HYM2",
        "label": "High-Yield OAS",
        "widen_trigger": 0.75,   # +75 bp off the trailing low
        "stress_level": 4.00,    # 400 bp — outright HY distress
    },
    "IG": {
        "fred_id": "BAMLC0A0CM",
        "label": "Investment-Grade OAS",
        "widen_trigger": 0.30,   # +30 bp off the trailing low
        "stress_level": 1.25,    # 125 bp — IG stress
    },
}


def evaluate_series(values: list[float], cfg: dict) -> list[dict]:
    """Pure signal logic over an ascending list of OAS values (latest last).

    Returns a list of {kind, severity, current, ...} signal dicts.
    """
    out: list[dict] = []
    if len(values) < 2:
        return out
    current = values[-1]
    window = values[-LOOKBACK:] if len(values) >= LOOKBACK else values
    low = min(window)
    widened = current - low

    if widened >= cfg["widen_trigger"]:
        sev = "HIGH" if widened >= 2 * cfg["widen_trigger"] else "MED"
        out.append({
            "kind": "SPREAD_WIDENING",
            "severity": sev,
            "current": current,
            "low": low,
            "widened_bp": round(widened * 100, 0),
        })

    if current >= cfg["stress_level"]:
        out.append({
            "kind": "SPREAD_STRESS",
            "severity": "HIGH",
            "current": current,
            "stress_level": cfg["stress_level"],
        })
    return out


def _ensure_table(state: State) -> None:
    with state.connection() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS c7_spreads (
                series TEXT,
                obs_date TEXT,
                oas REAL,
                PRIMARY KEY(series, obs_date)
            )
        """)


def _store(state: State, series: str, obs_date: str, oas: float) -> None:
    with state.connection() as c:
        c.execute(
            "INSERT INTO c7_spreads(series, obs_date, oas) VALUES(?,?,?) "
            "ON CONFLICT(series, obs_date) DO UPDATE SET oas=excluded.oas",
            (series, obs_date, oas),
        )


class Catalyst7(CatalystBase):
    name = "Credit Market Stress"

    def __init__(self, state: State | None = None, fetch=series_csv):
        self._state = state or State("c7")
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

        for sig in evaluate_series(values, cfg):
            dedup = f"c7_{sig['kind']}|{key}|{obs_date}"
            if self._state.seen("c7_signals", dedup):
                continue
            self._state.mark_seen("c7_signals", dedup)
            cur_bp = sig["current"] * 100
            if sig["kind"] == "SPREAD_WIDENING":
                subject = (f"[C7-{sig['severity']}] {cfg['label']} widening: "
                           f"{cur_bp:.0f}bp (+{sig['widened_bp']:.0f}bp off low)")
                body = (
                    f"Series:   {key} ({cfg['fred_id']})\n"
                    f"Date:     {obs_date}\n"
                    f"Current:  {cur_bp:.0f} bp\n"
                    f"90d low:  {sig['low']*100:.0f} bp\n"
                    f"Widened:  +{sig['widened_bp']:.0f} bp\n"
                )
                numbers = {
                    "series": key, "current_bp": round(cur_bp, 0),
                    "low_bp": round(sig["low"] * 100, 0),
                    "widened_bp": sig["widened_bp"], "obs_date": obs_date,
                }
            else:  # SPREAD_STRESS
                subject = (f"[C7-{sig['severity']}] {cfg['label']} at stress level: "
                           f"{cur_bp:.0f}bp ≥ {cfg['stress_level']*100:.0f}bp")
                body = (
                    f"Series:   {key} ({cfg['fred_id']})\n"
                    f"Date:     {obs_date}\n"
                    f"Current:  {cur_bp:.0f} bp\n"
                    f"Stress ≥: {cfg['stress_level']*100:.0f} bp\n"
                )
                numbers = {
                    "series": key, "current_bp": round(cur_bp, 0),
                    "stress_bp": round(cfg["stress_level"] * 100, 0),
                    "obs_date": obs_date,
                }
            alerts.append(Alert(
                catalyst="C7", severity=sig["severity"], subject=subject,
                body=append_context(body, "C7", sig["kind"], numbers=numbers),
            ))
        return alerts

    def run(self) -> list[Alert]:
        alerts: list[Alert] = []
        for key, cfg in SERIES.items():
            try:
                alerts.extend(self._check_series(key, cfg))
            except Exception as e:
                log.warning("c7.%s path failed: %s", key, e)
        return alerts


def _main(argv: list[str] | None = None) -> int:
    from catalysts.base import run_cli
    return run_cli(lambda args: Catalyst7(),
                   description="Catalyst 7: Credit market stress", argv=argv)


if __name__ == "__main__":
    raise SystemExit(_main())

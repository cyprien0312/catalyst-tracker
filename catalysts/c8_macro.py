"""Catalyst 8 — Macro Triggers (inflation / Fed path).

The classic balloon-popping combination is: inflation sticks → the Fed can't
cut → high valuations and high leverage are squeezed at the same time. The
research flags CPI re-accelerating (4.2% YoY in May 2026, highest since Apr
2023) as the live trigger. Cheap money is the common fuel of every bubble in
this tracker; this catalyst watches for it being taken away.

Sources (FRED keyless CSV):
- CPIAUCSL — CPI for All Urban Consumers (monthly index level).
- PCEPILFE — Core PCE (ex food & energy), the Fed's *actual* target metric.
             CPI is what the public watches; PCE is what the FOMC decides on,
             so a hot core-PCE print is the more direct "no cuts" signal.

Signals (computed from each monthly series):
- CPI_HOT / PCE_HOT       — YoY at/above the hot threshold (above the Fed's
                            comfort zone, blocks cuts). MED, escalates to HIGH.
- CPI_REACCEL / PCE_REACCEL — YoY higher than the prior month for two consecutive
                            months AND above the re-accel floor. Direction over
                            level. MED.
"""
from __future__ import annotations

from catalysts.base import Alert, CatalystBase
from lib.explanations import append_context
from lib.fred import series_csv
from lib.log import get_logger
from lib.state import State

log = get_logger(__name__)

CPI_SERIES = "CPIAUCSL"
PCE_SERIES = "PCEPILFE"     # Core PCE (ex food & energy) — the Fed's target

CPI_HOT_THRESHOLD = 3.5      # YoY % — above Fed comfort
CPI_HOT_HIGH = 4.5          # YoY % — clearly restrictive
CPI_REACCEL_FLOOR = 3.0     # YoY % — re-acceleration only matters above this

# Core PCE runs structurally cooler than headline CPI and targets 2.0%, so the
# thresholds sit lower: ≥3.0% is already "Fed can't cut" territory.
PCE_HOT_THRESHOLD = 3.0      # YoY % — clearly above the 2% target
PCE_HOT_HIGH = 3.5          # YoY % — restrictive
PCE_REACCEL_FLOOR = 2.5     # YoY % — re-acceleration only matters above this


def _yoy_series(monthly: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Convert a monthly index series to [(date, yoy_pct)] (ascending).

    Uses the value 12 observations earlier as the year-ago comparison.
    """
    out: list[tuple[str, float]] = []
    for i in range(12, len(monthly)):
        date_i, val_i = monthly[i]
        _, val_prior = monthly[i - 12]
        if val_prior:
            out.append((date_i, (val_i / val_prior - 1.0) * 100.0))
    return out


def _evaluate_yoy(monthly: list[tuple[str, float]], *, hot: float, hot_high: float,
                  reaccel_floor: float, hot_kind: str, reaccel_kind: str) -> list[dict]:
    """Pure signal logic over an ascending monthly index series.

    Shared by CPI and core-PCE — only the thresholds and signal-kind labels
    differ between the two metrics.
    """
    yoy = _yoy_series(monthly)
    out: list[dict] = []
    if not yoy:
        return out
    date, current = yoy[-1]

    if current >= hot:
        sev = "HIGH" if current >= hot_high else "MED"
        out.append({"kind": hot_kind, "severity": sev,
                    "date": date, "yoy": current})

    # Re-acceleration: two consecutive month-over-month increases in YoY.
    if len(yoy) >= 3 and current >= reaccel_floor:
        prev = yoy[-2][1]
        prev2 = yoy[-3][1]
        if current > prev > prev2:
            out.append({"kind": reaccel_kind, "severity": "MED",
                        "date": date, "yoy": current,
                        "yoy_prev": prev, "yoy_prev2": prev2})
    return out


def evaluate_cpi(monthly: list[tuple[str, float]]) -> list[dict]:
    """Pure signal logic over the ascending monthly CPI index series."""
    return _evaluate_yoy(monthly, hot=CPI_HOT_THRESHOLD, hot_high=CPI_HOT_HIGH,
                         reaccel_floor=CPI_REACCEL_FLOOR,
                         hot_kind="CPI_HOT", reaccel_kind="CPI_REACCEL")


def evaluate_pce(monthly: list[tuple[str, float]]) -> list[dict]:
    """Pure signal logic over the ascending monthly core-PCE index series."""
    return _evaluate_yoy(monthly, hot=PCE_HOT_THRESHOLD, hot_high=PCE_HOT_HIGH,
                         reaccel_floor=PCE_REACCEL_FLOOR,
                         hot_kind="PCE_HOT", reaccel_kind="PCE_REACCEL")


def _ensure_table(state: State) -> None:
    with state.connection() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS c8_macro (
                metric TEXT,
                obs_date TEXT,
                value REAL,
                PRIMARY KEY(metric, obs_date)
            )
        """)


def _store(state: State, metric: str, obs_date: str, value: float) -> None:
    with state.connection() as c:
        c.execute(
            "INSERT INTO c8_macro(metric, obs_date, value) VALUES(?,?,?) "
            "ON CONFLICT(metric, obs_date) DO UPDATE SET value=excluded.value",
            (metric, obs_date, value),
        )


# Per-metric config: drives both fetch loop and subject text.
METRICS = [
    {"series": CPI_SERIES, "label": "CPI", "store_key": "CPI_YOY",
     "evaluate": evaluate_cpi, "hot_threshold": CPI_HOT_THRESHOLD,
     "hot_kind": "CPI_HOT", "reaccel_kind": "CPI_REACCEL"},
    {"series": PCE_SERIES, "label": "Core PCE", "store_key": "PCE_YOY",
     "evaluate": evaluate_pce, "hot_threshold": PCE_HOT_THRESHOLD,
     "hot_kind": "PCE_HOT", "reaccel_kind": "PCE_REACCEL"},
]


class Catalyst8(CatalystBase):
    name = "Macro Triggers"

    def __init__(self, state: State | None = None, fetch=series_csv):
        self._state = state or State("c8")
        self._fetch = fetch
        _ensure_table(self._state)

    def _check_metric(self, cfg: dict) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            monthly = self._fetch(cfg["series"])
        except Exception as e:
            log.warning("c8.%s fetch failed: %s", cfg["store_key"], e)
            return alerts
        if not monthly:
            return alerts

        yoy = _yoy_series(monthly)
        if yoy:
            _store(self._state, cfg["store_key"], yoy[-1][0], round(yoy[-1][1], 2))

        for sig in cfg["evaluate"](monthly):
            dedup = f"c8_{sig['kind']}|{sig['date']}"
            if self._state.seen("c8_signals", dedup):
                continue
            self._state.mark_seen("c8_signals", dedup)
            if sig["kind"] == cfg["hot_kind"]:
                subject = (f"[C8-{sig['severity']}] {cfg['label']} YoY {sig['yoy']:.1f}% "
                           f"(≥ {cfg['hot_threshold']}%) — Fed cuts blocked")
                body = (
                    f"Metric:   {cfg['label']} YoY\nMonth:    {sig['date']}\n"
                    f"YoY:      {sig['yoy']:.2f}%\nThreshold: {cfg['hot_threshold']}%\n"
                )
                numbers = {"yoy_pct": round(sig["yoy"], 2),
                           "threshold_pct": cfg["hot_threshold"], "month": sig["date"]}
            else:  # *_REACCEL
                subject = (f"[C8-MED] {cfg['label']} YoY re-accelerating: "
                           f"{sig['yoy']:.1f}% (2 mo rising)")
                body = (
                    f"Metric:   {cfg['label']} YoY (re-acceleration)\nMonth:    {sig['date']}\n"
                    f"YoY:      {sig['yoy_prev2']:.2f}% → {sig['yoy_prev']:.2f}% → {sig['yoy']:.2f}%\n"
                )
                numbers = {"yoy_pct": round(sig["yoy"], 2),
                           "yoy_prev_pct": round(sig["yoy_prev"], 2),
                           "yoy_prev2_pct": round(sig["yoy_prev2"], 2),
                           "month": sig["date"]}
            alerts.append(Alert(
                catalyst="C8", severity=sig["severity"], subject=subject,
                body=append_context(body, "C8", sig["kind"], numbers=numbers),
            ))
        return alerts

    def run(self) -> list[Alert]:
        alerts: list[Alert] = []
        for cfg in METRICS:
            alerts.extend(self._check_metric(cfg))
        return alerts


def _main(argv: list[str] | None = None) -> int:
    from catalysts.base import run_cli
    return run_cli(lambda args: Catalyst8(),
                   description="Catalyst 8: Macro triggers", argv=argv)


if __name__ == "__main__":
    raise SystemExit(_main())

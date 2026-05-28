"""Catalyst 5 — Grid Bottlenecks / Power Constraints."""
from __future__ import annotations

from catalysts.base import Alert, CatalystBase
from lib.eia import henry_hub_strip
from lib.explanations import append_context
from lib.log import get_logger
from lib.state import State
from lib import grid_queues

log = get_logger(__name__)


HENRY_HUB_STRESS = 5.00          # USD/MMBtu — 12-month strip average
MOM_DROP_PCT = 5.0               # % MoM drop in queue total MW
WITHDRAWN_THRESHOLD = 5          # weekly new withdrawals of ≥100MW projects


def _ensure_table(state: State) -> None:
    with state.connection() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS c5_queues (
                iso TEXT,
                snapshot_date TEXT,
                total_mw REAL,
                count INTEGER,
                withdrawn_count INTEGER,
                withdrawn_mw_100plus INTEGER,
                PRIMARY KEY(iso, snapshot_date)
            )
        """)


def _store_snapshot(state: State, iso: str, snapshot_date: str, summary: dict) -> None:
    with state.connection() as c:
        c.execute(
            "INSERT INTO c5_queues(iso, snapshot_date, total_mw, count, withdrawn_count, withdrawn_mw_100plus) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(iso, snapshot_date) DO UPDATE SET "
            "total_mw=excluded.total_mw, count=excluded.count, "
            "withdrawn_count=excluded.withdrawn_count, "
            "withdrawn_mw_100plus=excluded.withdrawn_mw_100plus",
            (iso, snapshot_date, summary["total_mw"], summary["count"],
             summary["withdrawn_count"], summary["withdrawn_mw_100plus"]),
        )


def _prior_snapshot(state: State, iso: str, current_date: str) -> dict | None:
    with state.connection() as c:
        row = c.execute(
            "SELECT snapshot_date, total_mw, withdrawn_count FROM c5_queues "
            "WHERE iso=? AND snapshot_date<? ORDER BY snapshot_date DESC LIMIT 1",
            (iso, current_date),
        ).fetchone()
    if not row:
        return None
    return {"date": row[0], "total_mw": float(row[1]), "withdrawn_count": int(row[2])}


class Catalyst5(CatalystBase):
    name = "Grid Bottlenecks"

    def __init__(self, state: State | None = None,
                 fetch_pjm=grid_queues.pjm_active_queue,
                 fetch_caiso=grid_queues.caiso_queue,
                 fetch_henryhub=henry_hub_strip):
        self._state = state or State("c5")
        self._fetch_pjm = fetch_pjm
        self._fetch_caiso = fetch_caiso
        self._fetch_henryhub = fetch_henryhub
        _ensure_table(self._state)

    def _check_iso(self, iso: str, snapshot_date: str, fetch) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            df = fetch()
        except Exception as e:
            log.warning("c5.%s source failed: %s", iso.lower(), e)
            return alerts
        summary = grid_queues.summarize(df, iso)
        prior = _prior_snapshot(self._state, iso, snapshot_date)
        _store_snapshot(self._state, iso, snapshot_date, summary)

        if prior:
            prior_mw = prior["total_mw"]
            if prior_mw > 0:
                drop_pct = (prior_mw - summary["total_mw"]) / prior_mw * 100.0
                if drop_pct >= MOM_DROP_PCT:
                    key = f"c5_mw_drop|{iso}|{snapshot_date}"
                    if not self._state.seen("c5_signals", key):
                        self._state.mark_seen("c5_signals", key)
                        alerts.append(Alert(
                            catalyst="C5", severity="MED",
                            subject=f"[C5-MED] {iso}: queue MW down {drop_pct:.1f}% vs {prior['date']}",
                            body=append_context(
                                f"Total MW {summary['total_mw']:.0f} (was {prior_mw:.0f}). Snapshot {snapshot_date}.\n",
                                "C5", "MW_DROP",
                                numbers={
                                    "iso": iso,
                                    "mw_now": round(summary["total_mw"], 0),
                                    "mw_prior": round(prior_mw, 0),
                                    "drop_pct": round(drop_pct, 1),
                                    "prior_date": prior["date"],
                                    "snapshot_date": snapshot_date,
                                },
                            ),
                        ))
            new_withdrawn = summary["withdrawn_count"] - prior["withdrawn_count"]
            if new_withdrawn >= WITHDRAWN_THRESHOLD:
                key = f"c5_withdrawn|{iso}|{snapshot_date}"
                if not self._state.seen("c5_signals", key):
                    self._state.mark_seen("c5_signals", key)
                    alerts.append(Alert(
                        catalyst="C5", severity="HIGH",
                        subject=f"[C5-HIGH] {iso}: {new_withdrawn} new withdrawals vs {prior['date']}",
                        body=append_context(
                            f"Withdrawn count {summary['withdrawn_count']} (was {prior['withdrawn_count']}).\n",
                            "C5", "NEW_WITHDRAWALS",
                            numbers={
                                "iso": iso,
                                "withdrawn_now": summary["withdrawn_count"],
                                "withdrawn_prior": prior["withdrawn_count"],
                                "new_count": new_withdrawn,
                                "prior_date": prior["date"],
                                "snapshot_date": snapshot_date,
                            },
                        ),
                    ))
        return alerts

    def _check_henry_hub(self, snapshot_date: str) -> list[Alert]:
        alerts: list[Alert] = []
        strip = self._fetch_henryhub()
        if not strip:
            return alerts
        avg = sum(strip) / len(strip)
        if avg >= HENRY_HUB_STRESS:
            key = f"c5_hh_stress|{snapshot_date}"
            if not self._state.seen("c5_signals", key):
                self._state.mark_seen("c5_signals", key)
                alerts.append(Alert(
                    catalyst="C5", severity="MED",
                    subject=f"[C5-MED] Henry Hub 12mo strip avg ${avg:.2f}/MMBtu ≥ ${HENRY_HUB_STRESS:.2f}",
                    body=append_context(
                        f"Strip values: {strip}\n",
                        "C5", "HENRY_HUB_STRESS",
                        numbers={
                            "strip_avg": round(avg, 2),
                            "threshold": HENRY_HUB_STRESS,
                            "strip_min": round(min(strip), 2),
                            "strip_max": round(max(strip), 2),
                            "snapshot_date": snapshot_date,
                        },
                    ),
                ))
        return alerts

    def run(self) -> list[Alert]:
        import datetime as _dt
        snapshot_date = _dt.date.today().isoformat()
        alerts: list[Alert] = []
        try:
            alerts.extend(self._check_iso("PJM", snapshot_date, self._fetch_pjm))
        except Exception as e:
            log.warning("c5.pjm path failed: %s", e)
        try:
            alerts.extend(self._check_iso("CAISO", snapshot_date, self._fetch_caiso))
        except Exception as e:
            log.warning("c5.caiso path failed: %s", e)
        try:
            alerts.extend(self._check_henry_hub(snapshot_date))
        except Exception as e:
            log.warning("c5.henry_hub path failed: %s", e)
        return alerts


def _main(argv: list[str] | None = None) -> int:
    from catalysts.base import run_cli

    def _factory(args):
        if args.skip_iso:
            import pandas as pd
            empty = lambda: pd.DataFrame()
            return Catalyst5(fetch_pjm=empty, fetch_caiso=empty)
        return Catalyst5()

    def _extra(p):
        p.add_argument("--skip-iso", action="store_true",
                       help="skip live ISO XLSX downloads")

    return run_cli(_factory, description="Catalyst 5: Grid bottlenecks",
                   extra_args=_extra, argv=argv)


if __name__ == "__main__":
    raise SystemExit(_main())

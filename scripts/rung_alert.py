"""Immediate email when the buy-plan crosses a ladder rung or flips regime.

The daily digest renders the BUY PLAN card once a day at 09:00; this script
is the fast path — cron runs it hourly (bin/check_rungs.sh) so a rung
crossing emails within the hour of FRED publishing the close that crossed it.

Alert semantics:
  * A rung alerts once per *drawdown episode*: the idempotency key includes
    the ATH date, and the ATH only moves while no rung is triggered, so a
    recovery to a new high re-arms every rung for the next episode.
  * The 0% starter rung never alerts (it is triggered at every ATH).
  * A regime flip (A<->B) alerts on the change itself; the first ever run
    just records the baseline regime silently.

State lives in the shared `seen` table (namespaces `buyplan_rungs`,
`buyplan_regime`); alerts go through lib.notify.send_alert so they dedup,
persist to the `alerts` table, and show up on the dashboard like any
catalyst alert (tag `buyplan`).

    python scripts/rung_alert.py            # check + email
    python scripts/rung_alert.py --dry-run  # print would-be alerts, no state
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.log import get_logger
from lib.notify import send_alert
from lib.state import State

from scripts import regime_signal

log = get_logger(__name__)

RUNG_TABLE = "buyplan_rungs"
REGIME_TABLE = "buyplan_regime"


def rung_key(regime: str, thresh: float, ath_date: str) -> str:
    return f"{regime}:{thresh:.2f}:{ath_date}"


def new_crossings(plan: dict, state: State) -> list[dict]:
    """Triggered rungs not yet alerted for this (regime, ATH) episode."""
    out = []
    for r in plan["rungs"]:
        if not r["triggered"] or r["thresh"] >= 0:  # starter rung never alerts
            continue
        key = rung_key(plan["regime"], r["thresh"], plan["ndx"]["ath_date"])
        if state.seen(RUNG_TABLE, key):
            continue
        out.append({**r, "key": key})
    return out


def previous_regime(state: State) -> str | None:
    """Most recently recorded regime, or None on first ever run."""
    with state.connection() as c:
        row = c.execute(
            "SELECT key FROM seen WHERE table_name=? ORDER BY ts DESC LIMIT 1",
            (REGIME_TABLE,),
        ).fetchone()
    return row[0] if row else None


def rung_alert_content(plan: dict, rung: dict) -> tuple[str, str, str]:
    """(subject, body, severity) for a crossed rung."""
    action = f"deploy {rung['pct']}% of the ladder pool"
    if plan["regime"] == regime_signal.B and rung["thresh"] <= -0.50 + 1e-9:
        action += " — AFTER the stabilisation check passes"
    subject = (
        f"[BUYPLAN] rung crossed: {rung['label']} "
        f"({rung['thresh']*100:.0f}%) — {action} (Regime {plan['regime']})"
    )
    body = (
        f"Rung crossed: {rung['label']} @ NDX {rung['level']:,.0f} "
        f"({rung['thresh']*100:.0f}% off ATH) → {action}.\n\n"
        + regime_signal.render_text(plan)
    )
    return subject, body, "HIGH"


def flip_alert_content(plan: dict, prev: str) -> tuple[str, str, str]:
    """(subject, body, severity) for a regime flip."""
    now = plan["regime"]
    if now == regime_signal.B:
        headline = "fuse lit — FREEZE the fast ladder, hold the reserve"
        severity = "CRITICAL"
    else:
        headline = "fuses clear — back to the shallow ladder"
        severity = "MED"
    fuse_note = f" (lit: {', '.join(plan['fuses'])})" if plan["fuses"] else ""
    subject = f"[BUYPLAN] regime {prev} → {now}{fuse_note}: {headline}"
    body = (
        f"Buy-plan regime flipped {prev} → {now}{fuse_note}.\n"
        f"{headline}.\n\n" + regime_signal.render_text(plan)
    )
    return subject, body, severity


def run(dry_run: bool = False, state: State | None = None) -> int:
    plan = regime_signal.live_plan()
    if not plan:
        log.warning("rung_alert.skip reason=index_fetch_failed")
        return 0
    state = state or State("rung_alert")

    alerts: list[tuple[str, str, str]] = []
    prev = previous_regime(state)
    if prev is not None and prev != plan["regime"]:
        alerts.append(flip_alert_content(plan, prev))
    crossings = new_crossings(plan, state)
    alerts += [rung_alert_content(plan, r) for r in crossings]

    if dry_run:
        if not alerts:
            print(
                f"no new rung/regime alerts (regime {plan['regime']}, "
                f"drawdown {plan['ndx']['drawdown']*100:+.1f}%)"
            )
        for subject, body, severity in alerts:
            print(f"--- {severity}: {subject}\n{body}\n")
        return 0

    for subject, body, severity in alerts:
        send_alert(subject, body, severity=severity, catalyst="buyplan", state=state)
    # marks happen only after send_alert returns, so an SMTP failure retries
    # on the next cron pass instead of being swallowed
    for r in crossings:
        state.mark_seen(RUNG_TABLE, r["key"])
    if prev != plan["regime"]:
        state.mark_seen(REGIME_TABLE, plan["regime"])
    if alerts:
        log.info("rung_alert.sent count=%d", len(alerts))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="buy-plan rung/regime alerter")
    p.add_argument("--dry-run", action="store_true",
                   help="print would-be alerts; no email, no state writes")
    args = p.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

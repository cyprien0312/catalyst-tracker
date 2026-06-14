"""Daily digest e-mail for catalyst-tracker.

A once-a-day heartbeat that summarises all nine catalysts in priority order
(fuses first), with current gauge readings for the numeric signals and a
7-day alert roll-up for the event-driven ones. Sent via Gmail SMTP, separate
from the per-catalyst alert path (no dedup — it goes out every day).

    python scripts/daily_report.py            # send
    python scripts/daily_report.py --dry-run  # print to stdout
"""
from __future__ import annotations

import argparse
import datetime as dt
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import HYPERSCALERS, NEOCLOUDS, require_env
from lib.state import State

DASHBOARD = "https://cyprien0312.github.io/catalyst-tracker/"

FIRING, WATCH, QUIET = "🔴 FIRING", "🟡 watch", "🟢 quiet"


# ---------- numeric gauges (re-fetch live so the digest is always current) ----------

def gauge_c7() -> tuple[str, list[str]]:
    from catalysts.c7_credit import SERIES, LOOKBACK, evaluate_series
    from lib.fred import series_csv
    lines, status = [], QUIET
    for key, cfg in SERIES.items():
        series = series_csv(cfg["fred_id"])
        if not series:
            lines.append(f"    {cfg['label']}: n/a (fetch failed)")
            continue
        values = [v for _, v in series]
        current = values[-1]
        low = min(values[-LOOKBACK:]) if len(values) >= LOOKBACK else min(values)
        widened_bp = (current - low) * 100
        trig_bp = cfg["widen_trigger"] * 100
        sigs = evaluate_series(values, cfg)
        if sigs:
            status = FIRING
        elif widened_bp >= trig_bp / 2 and status == QUIET:
            status = WATCH
        lines.append(
            f"    {cfg['label']}: {current*100:.0f}bp · +{widened_bp:.0f}bp off 90d-low "
            f"(fire ≥+{trig_bp:.0f}) · stress ≥{cfg['stress_level']*100:.0f}"
        )
    return status, lines


def gauge_c8() -> tuple[str, list[str]]:
    from catalysts.c8_macro import CPI_SERIES, CPI_HOT_THRESHOLD, CPI_HOT_HIGH, _yoy_series, evaluate_cpi
    from lib.fred import series_csv
    monthly = series_csv(CPI_SERIES)
    if not monthly:
        return QUIET, ["    CPI: n/a (fetch failed)"]
    yoy = _yoy_series(monthly)
    if not yoy:
        return QUIET, ["    CPI: insufficient history"]
    date, val = yoy[-1]
    sigs = {s["kind"] for s in evaluate_cpi(monthly)}
    status = FIRING if "CPI_HOT" in sigs else (WATCH if val >= 3.0 else QUIET)
    hot = "✓" if val >= CPI_HOT_THRESHOLD else "✗"
    extra = " · re-accel 2mo" if "CPI_REACCEL" in sigs else ""
    return status, [f"    CPI YoY {val:.2f}% ({date}) · hot ≥{CPI_HOT_THRESHOLD} {hot}, "
                    f"restrictive ≥{CPI_HOT_HIGH}{extra}"]


def gauge_c9() -> tuple[str, list[str]]:
    from catalysts.c9_crypto import _sma, MAYER_HOT, MAYER_HIGH, evaluate
    from lib.crypto import btc_daily_closes
    series = btc_daily_closes()
    if not series or len(series) < 200:
        return QUIET, ["    BTC: n/a (insufficient data)"]
    closes = [p for _, p in series]
    sma200 = _sma(closes, 200)
    mayer = closes[-1] / sma200 if sma200 else None
    kinds = {s["kind"] for s in evaluate(closes)}
    if "PI_CYCLE_TOP" in kinds or "MAYER_HOT" in kinds:
        status = FIRING
    elif mayer and mayer >= 2.0:
        status = WATCH
    else:
        status = QUIET
    zone = "value zone" if (mayer and mayer < 1.0) else ("froth" if (mayer and mayer >= MAYER_HOT) else "neutral")
    pi = " · Pi-Cycle TOP" if "PI_CYCLE_TOP" in kinds else ""
    return status, [f"    BTC Mayer {mayer:.2f} (hot ≥{MAYER_HOT}, extreme ≥{MAYER_HIGH}) · {zone}{pi}"]


def gauge_c4(state: State) -> tuple[str, list[str]]:
    cik_to_ticker = {v: k for k, v in HYPERSCALERS.items()}
    rows = []
    try:
        with state.connection() as c:
            # latest period per cik
            rows = c.execute("""
                SELECT x.cik, x.period_end, x.ratio, x.fcf_ttm FROM c4_xbrl x
                JOIN (SELECT cik, MAX(period_end) mp FROM c4_xbrl GROUP BY cik) m
                  ON x.cik=m.cik AND x.period_end=m.mp
            """).fetchall()
    except Exception:
        return QUIET, ["    no XBRL snapshots yet"]
    if not rows:
        return QUIET, ["    no XBRL snapshots yet"]
    status = QUIET
    worst_ratio = max(rows, key=lambda r: r[2] if r[2] is not None else -1)
    worst_fcf = min(rows, key=lambda r: r[3] if r[3] is not None else 1e18)
    wr_t = cik_to_ticker.get(worst_ratio[0], worst_ratio[0])
    wf_t = cik_to_ticker.get(worst_fcf[0], worst_fcf[0])
    if (worst_ratio[2] or 0) >= 1.10 or (worst_fcf[3] or 0) < 0:
        status = FIRING
    elif (worst_ratio[2] or 0) >= 1.00:
        status = WATCH
    lines = [
        f"    max ratio: {wr_t} {(worst_ratio[2] or 0)*100:.0f}% (cross ≥110)",
        f"    min FCF:   {wf_t} ${(worst_fcf[3] or 0)/1e9:.1f}B",
    ]
    return status, lines


# ---------- event-driven roll-up (alerts table, last 7d) ----------

_SEV_RANK = {"LOG": 0, "MED": 1, "HIGH": 2, "CRITICAL": 3}


def recent_by_catalyst(state: State, tag: str, days: int = 7) -> tuple[str, int, str]:
    """Return (status, count, breakdown_str) for a catalyst over the window.

    Status reflects the top severity: FIRING if any HIGH+, WATCH if only MED,
    QUIET if none. breakdown_str is like '2 CRIT, 576 MED'.
    """
    since = int(time.time()) - days * 86400
    rows = []
    try:
        with state.connection() as c:
            rows = c.execute(
                "SELECT severity, COUNT(*) FROM alerts WHERE LOWER(catalyst)=? AND ts>=? GROUP BY severity",
                (tag.lower(), since),
            ).fetchall()
    except Exception:
        return QUIET, 0, ""
    if not rows:
        return QUIET, 0, ""
    counts = {sev: n for sev, n in rows}
    total = sum(counts.values())
    top = max(_SEV_RANK.get(s, 0) for s in counts)
    status = FIRING if top >= _SEV_RANK["HIGH"] else WATCH
    order = ["CRITICAL", "HIGH", "MED", "LOG"]
    label = {"CRITICAL": "CRIT", "HIGH": "HIGH", "MED": "MED", "LOG": "LOG"}
    parts = [f"{counts[s]} {label[s]}" for s in order if counts.get(s)]
    return status, total, ", ".join(parts)


def _norm_subject(subject: str) -> str:
    """Strip the [Cx-SEV] prefix and the ' - Source' suffix for dedup."""
    s = subject
    if s.startswith("["):
        s = s.split("]", 1)[-1].strip()
    if " - " in s:
        s = s.rsplit(" - ", 1)[0].strip()
    return s


def notable_high_plus(state: State, days: int = 7, cap: int = 12) -> list[str]:
    """Deduped HIGH/CRITICAL subjects across all catalysts in the window —
    the actionable content, cutting through MED noise."""
    since = int(time.time()) - days * 86400
    try:
        with state.connection() as c:
            rows = c.execute(
                "SELECT catalyst, severity, subject FROM alerts "
                "WHERE ts>=? AND severity IN ('HIGH','CRITICAL') ORDER BY ts DESC",
                (since,),
            ).fetchall()
    except Exception:
        return []
    seen, out = set(), []
    for cat, sev, subject in rows:
        norm = _norm_subject(subject)
        if norm in seen:
            continue
        seen.add(norm)
        out.append(f"    [{cat.upper()}-{sev}] {norm[:88]}")
        if len(out) >= cap:
            break
    return out


# ---------- compose ----------

def build_report() -> tuple[str, str]:
    state = State("daily_report")
    today = dt.date.today().isoformat()

    s7, l7 = gauge_c7()
    s4, l4 = gauge_c4(state)
    s8, l8 = gauge_c8()
    s9, l9 = gauge_c9()
    s2, n2, b2 = recent_by_catalyst(state, "c2")
    s1, n1, b1 = recent_by_catalyst(state, "c1")
    s6, n6, b6 = recent_by_catalyst(state, "c6")
    s3, n3, b3 = recent_by_catalyst(state, "c3")
    s5, n5, b5 = recent_by_catalyst(state, "c5")

    statuses = [s7, s2, s4, s1, s8, s6, s3, s5, s9]
    firing = sum(1 for s in statuses if s == FIRING)
    watch = sum(1 for s in statuses if s == WATCH)
    quiet = sum(1 for s in statuses if s == QUIET)

    L = []
    L.append(f"catalyst-tracker — Daily Digest · {today}")
    L.append("=" * 46)
    L.append(f"Status: 🔴 {firing} firing · 🟡 {watch} watch · 🟢 {quiet} quiet")
    L.append(f"Dashboard: {DASHBOARD}")
    L.append("")
    L.append("── FUSES (watch for the break) ───────────────")
    L.append(f"[1] C7 Credit Market Stress        {s7}")
    L.extend(l7)
    L.append(f"[2] C2 Neocloud Distress           {s2}")
    L.append(f"    {n2} alert(s) in 7d" + (f" ({b2})" if b2 else "") + f" · watching {'/'.join(NEOCLOUDS)}")
    L.append("")
    L.append("── HARD DATA (structural) ────────────────────")
    L.append(f"[3] C4 Hyperscaler Capex/OCF       {s4}")
    L.extend(l4)
    L.append(f"[4] C1 GPU Depreciation            {s1}")
    L.append(f"    {n1} useful-life/impairment filing(s) in 7d" + (f" ({b1})" if b1 else ""))
    L.append("")
    L.append("── BACKGROUND / LEADING ──────────────────────")
    L.append(f"[5] C8 Macro / CPI                 {s8}")
    L.extend(l8)
    L.append(f"[6] C6 Memory/Storage              {s6}")
    L.append(f"    {n6} price alert(s) in 7d" + (f" ({b6})" if b6 else ""))
    L.append("")
    L.append("── LAGGING / CROSS-ASSET ─────────────────────")
    L.append(f"[7] C3 OpenAI Stress               {s3}")
    L.append(f"    {n3} in 7d" + (f" ({b3})" if b3 else "") + " — mostly IPO chatter")
    L.append(f"[8] C5 Grid Bottlenecks            {s5}    ({n5} in 7d)")
    L.append(f"[9] C9 Crypto Cycle Top            {s9}")
    L.extend(l9)
    L.append("")
    L.append("── Notable (HIGH+) last 7d ───────────────────")
    notable = notable_high_plus(state)
    L.extend(notable if notable else ["    (none)"])
    L.append("")
    L.append("Priority order: C7→C2→C4→C1→C8→C6→C3→C5→C9 (fuses → hard data → background → lagging)")

    subject = f"[catalyst-tracker] Daily digest {today} · 🔴{firing} 🟡{watch} 🟢{quiet}"
    return subject, "\n".join(L)


def send(subject: str, body: str) -> None:
    gmail_user = require_env("GMAIL_USER")
    gmail_pw = require_env("GMAIL_APP_PASSWORD")
    alert_to = require_env("ALERT_TO")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = alert_to
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(gmail_user, gmail_pw)
        s.send_message(msg)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="catalyst-tracker daily digest")
    p.add_argument("--dry-run", action="store_true", help="print instead of emailing")
    args = p.parse_args(argv)
    subject, body = build_report()
    if args.dry_run:
        print(subject)
        print(body)
    else:
        send(subject, body)
        print("daily digest sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

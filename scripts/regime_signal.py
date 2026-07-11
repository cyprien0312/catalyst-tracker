"""Nasdaq-100 buy-plan signal, keyed off the catalyst fuses.

NDX is the *trigger* (highest-beta, most AI-concentrated tell); the buy
action applies to the whole portfolio (IVV/BGBL core + satellites), not just
a Nasdaq-100 tracker. An SPX drawdown reference line is carried alongside
because the IVV/BGBL core draws down shallower than NDX (-20% NDX is
typically -13..-15% SPX).

Two regimes decide which ladder you're on:

  Regime A — "healthy correction" (no fuse lit): buy *speed*. Corrections are
      short and get bought back fast, so deploy on a shallow drawdown ladder.
  Regime B — "bubble deflation" (C7 credit or C2 neocloud FIRING): buy
      *patience*. A real bust is a multi-quarter 40-70% grind, so freeze the
      fast ladder, keep the reserve, and only deploy on deep rungs once it
      stabilises.

The fuse that flips you A -> B is exactly what the tracker is built to catch:
C7 (credit spreads) and C2 (neocloud distress). Everything else is a
thermometer and does not move the regime.

    python scripts/regime_signal.py            # print the plan
    python scripts/regime_signal.py --json      # machine-readable
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.index_quote import ndx_drawdown, spx_drawdown
from lib.state import State

# (drawdown threshold from ATH, tranche % of the AI bucket, label)
# Regime A — deep-heavy ladder, max 60% deployed, 40% reserve held back.
# Weights lean into the deeper rungs (user preference: pay up for real dips,
# not for -10% noise).
REGIME_A_LADDER = [
    (0.00, 10, "starter · FOMO insurance"),
    (-0.10, 10, "dip 1"),
    (-0.15, 15, "dip 2"),
    (-0.20, 25, "dip 3"),
]
# Regime B — deep ladder for a real bust; the last rung needs stabilisation.
REGIME_B_LADDER = [
    (-0.30, 10, "knife 1 · fuse active"),
    (-0.40, 10, "knife 2"),
    (-0.50, 20, "backup-the-truck · needs stabilisation"),
]

A, B = "A", "B"


def _fuse_state(rows) -> tuple[bool, list[str]]:
    """From daily_report rows, is a fuse (C7/C2) FIRING? Returns (lit, which)."""
    from scripts.daily_report import FIRING
    by_id = {r.id: r for r in rows}
    lit = []
    for fid in ("C7", "C2"):
        r = by_id.get(fid)
        if r is not None and r.status == FIRING:
            lit.append(fid)
    return bool(lit), lit


def build_plan(ndx: dict | None, fuse_lit: bool, fuses: list[str],
               spx: dict | None = None) -> dict | None:
    """Assemble the buy-plan model from a drawdown reading + fuse state.

    ``spx`` is an optional S&P 500 drawdown reading rendered as a reference
    line for the IVV/BGBL core; the ladder itself keys off NDX only.
    """
    if not ndx:
        return None
    dd = ndx["drawdown"]
    regime = B if fuse_lit else A
    ladder_cfg = REGIME_B_LADDER if regime == B else REGIME_A_LADDER

    rungs, cumulative, next_rung = [], 0, None
    for thresh, pct, label in ladder_cfg:
        level = ndx["ath"] * (1 + thresh)
        triggered = dd <= thresh + 1e-9
        if triggered:
            cumulative += pct
        elif next_rung is None:
            next_rung = {"thresh": thresh, "pct": pct, "label": label, "level": level}
        rungs.append({
            "thresh": thresh, "pct": pct, "label": label,
            "level": level, "triggered": triggered,
        })
    reserve = max(0, 100 - sum(p for _, p, _ in REGIME_A_LADDER)) if regime == A else 0
    return {
        "ndx": ndx,
        "spx": spx,
        "regime": regime,
        "fuses": fuses,
        "rungs": rungs,
        "cumulative_target": cumulative,
        "reserve": reserve,
        "next_rung": next_rung,
        # the deep Regime-B rung only fires with a manual stabilisation check
        "needs_stabilisation": regime == B and dd <= -0.50 + 1e-9,
    }


# ---------- rendering ----------

_REGIME_LABEL = {
    A: "Regime A · 健康回调（引信未响）· buy speed",
    B: "Regime B · 泡沫破裂（引信亮）· buy patience",
}


def render_text(plan: dict | None) -> str:
    if not plan:
        return "★ BUY PLAN — U100/NDX: n/a (index fetch failed)"
    n = plan["ndx"]
    L = [
        "★ BUY PLAN — NDX trigger · portfolio ladder",
        f"NDX {n['current']:,.0f} · ATH {n['ath']:,.0f} ({n['ath_date']}) · "
        f"drawdown {n['drawdown']*100:+.1f}%  [{n['date']}]",
    ]
    s = plan.get("spx")
    if s:
        L.append(
            f"SPX {s['current']:,.0f} · drawdown {s['drawdown']*100:+.1f}% "
            f"(ref — IVV/BGBL core draws down shallower than NDX)"
        )
    L += [
        _REGIME_LABEL[plan["regime"]]
        + (f" — lit: {', '.join(plan['fuses'])}" if plan["fuses"] else ""),
        f"Cumulative target now: {plan['cumulative_target']}% deployed"
        + (f" · reserve held {plan['reserve']}%" if plan["reserve"] else ""),
        "",
    ]
    for r in plan["rungs"]:
        mark = "✅" if r["triggered"] else "⬜"
        arrow = ""
        nr = plan["next_rung"]
        if nr and not r["triggered"] and r["thresh"] == nr["thresh"]:
            arrow = "  ← next"
        L.append(
            f"  {mark} {r['thresh']*100:>4.0f}%  {r['label']:<34} "
            f"{r['pct']:>3}%  @ NDX {r['level']:,.0f}{arrow}"
        )
    if plan["regime"] == B:
        L.append("")
        L.append("  ⚠ Regime B: fast ladder FROZEN. Deep rung needs stabilisation —")
        L.append("    C7 stops widening / starts tightening, OR 4-6wk no new 20d-low.")
    return "\n".join(L)


# Compact HTML card for embedding in the daily digest.
_C = {A: "#27ae60", B: "#c0392b"}


def render_html_card(plan: dict | None) -> str:
    if not plan:
        return ""
    n = plan["ndx"]
    col = _C[plan["regime"]]
    rows_html = ""
    for r in plan["rungs"]:
        nr = plan["next_rung"]
        is_next = nr and not r["triggered"] and r["thresh"] == nr["thresh"]
        mark = "✅" if r["triggered"] else ("➡️" if is_next else "⬜")
        bg = "#eef9f0" if r["triggered"] else ("#fff7ed" if is_next else "#fff")
        rows_html += (
            f'<tr style="background:{bg};"><td style="padding:5px 10px;font-size:12.5px;color:#2a3344;">'
            f'{mark} <b>{r["thresh"]*100:.0f}%</b> · {r["label"]}</td>'
            f'<td style="padding:5px 10px;font-size:12.5px;color:#1a2230;font-weight:600;text-align:right;">{r["pct"]}%</td>'
            f'<td style="padding:5px 10px;font-size:12px;color:#566;text-align:right;">NDX {r["level"]:,.0f}</td></tr>'
        )
    s = plan.get("spx")
    spx_html = (
        f'<div style="font-size:12px;color:#566;margin:-2px 0 5px;">'
        f'SPX {s["current"]:,.0f} · drawdown {s["drawdown"]*100:+.1f}% '
        f'<span style="color:#8a94a3;">(ref · IVV/BGBL core)</span></div>'
        if s else ""
    )
    fuse_note = (f' · lit: {", ".join(plan["fuses"])}' if plan["fuses"] else "")
    stab = (
        '<div style="font-size:12px;color:#c0392b;margin-top:8px;">⚠ Fast ladder frozen — '
        'deep rung needs stabilisation (C7 stops widening, or 4-6wk no new 20d-low).</div>'
        if plan["regime"] == B else ""
    )
    return f"""
  <div style="background:#fff;border:1px solid #eef0f2;border-left:4px solid {col};border-radius:0 8px 8px 0;padding:14px 18px;margin:10px 0;">
    <div style="font-size:11px;font-weight:700;letter-spacing:1.2px;color:{col};">★ BUY PLAN · NDX TRIGGER</div>
    <div style="font-size:14px;color:#1a2230;font-weight:600;margin:5px 0;">
      NDX {n['current']:,.0f} · drawdown {n['drawdown']*100:+.1f}% off ATH {n['ath']:,.0f}
    </div>
    {spx_html}
    <div style="font-size:12.5px;color:{col};font-weight:600;">Regime {plan['regime']}{fuse_note} · target {plan['cumulative_target']}% deployed{(' · reserve ' + str(plan['reserve']) + '%') if plan['reserve'] else ''}</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px;border:1px solid #f0f0f2;border-radius:6px;overflow:hidden;">{rows_html}</table>
    {stab}
  </div>"""


def plan_from_rows(rows) -> dict | None:
    """Build the plan using fuse statuses already computed in a daily report."""
    fuse_lit, fuses = _fuse_state(rows)
    return build_plan(ndx_drawdown(), fuse_lit, fuses, spx=spx_drawdown())


def live_plan() -> dict | None:
    """Standalone: fetch live fuse statuses + drawdown and build the plan."""
    from scripts.daily_report import gauge_c7, recent_by_catalyst, FIRING
    state = State("regime_signal")
    s7, _ = gauge_c7()
    s2, _, _ = recent_by_catalyst(state, "c2")
    fuses = [fid for fid, st in (("C7", s7), ("C2", s2)) if st == FIRING]
    return build_plan(ndx_drawdown(), bool(fuses), fuses, spx=spx_drawdown())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="U100/NDX regime + buy-plan signal")
    p.add_argument("--json", action="store_true", help="emit the plan as JSON")
    args = p.parse_args(argv)
    plan = live_plan()
    if args.json:
        import json
        print(json.dumps(plan, default=str, indent=2))
    else:
        print(render_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Daily digest e-mail for catalyst-tracker.

A once-a-day heartbeat summarising all ten catalysts in priority order
(fuses first), with:
  - live gauge readings for the numeric signals (C7/C8/C10/C9) and C4 from XBRL,
  - a 7-day severity roll-up for the event-driven ones,
  - a deduped HIGH+ "notable" section that cuts through MED noise,
  - a FOCUS note (LLM-written analysis of the single most important thing
    today, with a rule-based fallback),
  - an HTML body (with a plain-text fallback part).

    python scripts/daily_report.py            # send
    python scripts/daily_report.py --dry-run  # print text body to stdout
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import HYPERSCALERS, NEOCLOUDS
from lib.email_send import send_email
from lib import knowledge, llm
from lib.state import State
from scripts import regime_signal

DASHBOARD = "https://cyprien0312.github.io/catalyst-tracker/"

FIRING, WATCH, QUIET = "FIRING", "watch", "quiet"
_DOT = {FIRING: "🔴", WATCH: "🟡", QUIET: "🟢"}
_COLOR = {FIRING: "#c0392b", WATCH: "#e67e22", QUIET: "#27ae60"}

TIERS = [
    ("FUSES", "watch for the break"),
    ("HARD DATA", "structural deterioration"),
    ("BACKGROUND", "regime / leading"),
    ("LAGGING", "slower / cross-asset"),
]


@dataclass
class Row:
    id: str
    name: str
    tier: str
    status: str
    lines: list[str] = field(default_factory=list)


# ---------- numeric gauges (re-fetch live so the digest is always current) ----------

def gauge_c7() -> tuple[str, list[str]]:
    from catalysts.c7_credit import SERIES, LOOKBACK, evaluate_series
    from lib.fred import series_csv
    lines, status = [], QUIET
    for cfg in SERIES.values():
        series = series_csv(cfg["fred_id"])
        if not series:
            lines.append(f"{cfg['label']}: n/a (fetch failed)")
            continue
        values = [v for _, v in series]
        current = values[-1]
        low = min(values[-LOOKBACK:]) if len(values) >= LOOKBACK else min(values)
        widened_bp = (current - low) * 100
        trig_bp = cfg["widen_trigger"] * 100
        if evaluate_series(values, cfg):
            status = FIRING
        elif widened_bp >= trig_bp / 2 and status == QUIET:
            status = WATCH
        lines.append(
            f"{cfg['label']}: {current*100:.0f}bp · +{widened_bp:.0f}bp off 90d-low "
            f"(fire ≥+{trig_bp:.0f}) · stress ≥{cfg['stress_level']*100:.0f}"
        )
    return status, lines


def gauge_c8() -> tuple[str, list[str]]:
    from catalysts.c8_macro import (
        CPI_SERIES, CPI_HOT_THRESHOLD, CPI_HOT_HIGH,
        PCE_SERIES, PCE_HOT_THRESHOLD, PCE_HOT_HIGH, PCE_REACCEL_FLOOR,
        _yoy_series, evaluate_cpi, evaluate_pce)
    from lib.fred import series_csv
    lines: list[str] = []
    status = QUIET

    def _bump(new: str) -> None:
        nonlocal status
        order = {QUIET: 0, WATCH: 1, FIRING: 2}
        if order[new] > order[status]:
            status = new

    # CPI (public-facing)
    monthly = series_csv(CPI_SERIES)
    if not monthly:
        lines.append("CPI: n/a (fetch failed)")
    else:
        yoy = _yoy_series(monthly)
        if not yoy:
            lines.append("CPI: insufficient history")
        else:
            date, val = yoy[-1]
            sigs = {s["kind"] for s in evaluate_cpi(monthly)}
            _bump(FIRING if "CPI_HOT" in sigs else (WATCH if val >= 3.0 else QUIET))
            hot = "✓" if val >= CPI_HOT_THRESHOLD else "✗"
            extra = " · re-accel 2mo" if "CPI_REACCEL" in sigs else ""
            lines.append(f"CPI YoY {val:.2f}% ({date}) · hot ≥{CPI_HOT_THRESHOLD} {hot}, "
                         f"restrictive ≥{CPI_HOT_HIGH}{extra}")

    # Core PCE (the Fed's actual target)
    pce = series_csv(PCE_SERIES)
    if not pce:
        lines.append("Core PCE: n/a (fetch failed)")
    else:
        yoy = _yoy_series(pce)
        if not yoy:
            lines.append("Core PCE: insufficient history")
        else:
            date, val = yoy[-1]
            sigs = {s["kind"] for s in evaluate_pce(pce)}
            _bump(FIRING if "PCE_HOT" in sigs else (WATCH if val >= PCE_REACCEL_FLOOR else QUIET))
            hot = "✓" if val >= PCE_HOT_THRESHOLD else "✗"
            extra = " · re-accel 2mo" if "PCE_REACCEL" in sigs else ""
            lines.append(f"Core PCE YoY {val:.2f}% ({date}) · hot ≥{PCE_HOT_THRESHOLD} {hot}, "
                         f"restrictive ≥{PCE_HOT_HIGH}{extra}")

    return status, lines


def gauge_c10() -> tuple[str, list[str]]:
    from catalysts.c10_liquidity import SERIES, LOOKBACK, evaluate_series, _fmt
    from lib.fred import series_csv
    lines, status = [], QUIET
    for cfg in SERIES.values():
        series = series_csv(cfg["fred_id"])
        if not series:
            lines.append(f"{cfg['label']}: n/a (fetch failed)")
            continue
        values = [v for _, v in series]
        current = values[-1]
        low = min(values[-LOOKBACK:]) if len(values) >= LOOKBACK else min(values)
        if cfg["mode"] == "pct":
            rise = (current / low - 1.0) * 100.0 if low else 0.0
            move = f"+{rise:.1f}% off 90d-low (fire ≥+{cfg['rise_trigger']:.1f}%)"
        else:
            rise = current - low
            move = f"+{rise*100:.0f}bp off 90d-low (fire ≥+{cfg['rise_trigger']*100:.0f}bp)"
        if evaluate_series(values, cfg):
            status = FIRING
        elif rise >= cfg["rise_trigger"] / 2 and status == QUIET:
            status = WATCH
        stress = (f" · restrictive ≥{cfg['stress_level']:.2f}%"
                  if cfg.get("stress_level") is not None else "")
        lines.append(f"{cfg['label']}: {_fmt(current, cfg['unit'])} · {move}{stress}")
    return status, lines


def gauge_c9() -> tuple[str, list[str]]:
    from catalysts.c9_crypto import _sma, MAYER_HOT, MAYER_HIGH, evaluate
    from lib.crypto import btc_daily_closes
    series = btc_daily_closes()
    if not series or len(series) < 200:
        return QUIET, ["BTC: n/a (insufficient data)"]
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
    return status, [f"BTC Mayer {mayer:.2f} (hot ≥{MAYER_HOT}, extreme ≥{MAYER_HIGH}) · {zone}{pi}"]


def gauge_c4(state: State) -> tuple[str, list[str]]:
    cik_to_ticker = {v: k for k, v in HYPERSCALERS.items()}
    try:
        with state.connection() as c:
            rows = c.execute("""
                SELECT x.cik, x.period_end, x.ratio, x.fcf_ttm FROM c4_xbrl x
                JOIN (SELECT cik, MAX(period_end) mp FROM c4_xbrl GROUP BY cik) m
                  ON x.cik=m.cik AND x.period_end=m.mp
            """).fetchall()
    except Exception:
        return QUIET, ["no XBRL snapshots yet"]
    if not rows:
        return QUIET, ["no XBRL snapshots yet"]
    status = QUIET
    worst_ratio = max(rows, key=lambda r: r[2] if r[2] is not None else -1)
    worst_fcf = min(rows, key=lambda r: r[3] if r[3] is not None else 1e18)
    wr_t = cik_to_ticker.get(worst_ratio[0], worst_ratio[0])
    wf_t = cik_to_ticker.get(worst_fcf[0], worst_fcf[0])
    if (worst_ratio[2] or 0) >= 1.10 or (worst_fcf[3] or 0) < 0:
        status = FIRING
    elif (worst_ratio[2] or 0) >= 1.00:
        status = WATCH
    return status, [
        f"max ratio: {wr_t} {(worst_ratio[2] or 0)*100:.0f}% (cross ≥110)",
        f"min FCF: {wf_t} ${(worst_fcf[3] or 0)/1e9:.1f}B",
    ]


# ---------- event-driven roll-up (alerts table, last 7d) ----------

_SEV_RANK = {"LOG": 0, "MED": 1, "HIGH": 2, "CRITICAL": 3}


def recent_by_catalyst(state: State, tag: str, days: int = 7) -> tuple[str, int, str]:
    since = int(time.time()) - days * 86400
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
    label = {"CRITICAL": "CRIT", "HIGH": "HIGH", "MED": "MED", "LOG": "LOG"}
    parts = [f"{counts[s]} {label[s]}" for s in ["CRITICAL", "HIGH", "MED", "LOG"] if counts.get(s)]
    return status, total, ", ".join(parts)


def _norm_subject(subject: str) -> str:
    s = subject
    if s.startswith("["):
        s = s.split("]", 1)[-1].strip()
    if " - " in s:
        s = s.rsplit(" - ", 1)[0].strip()
    return s


def notable_high_plus(state: State, days: int = 7, cap: int = 12) -> list[tuple[str, str, str]]:
    """Deduped (catalyst, severity, subject) HIGH/CRITICAL across the window."""
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
        out.append((cat.upper(), sev, norm[:96]))
        if len(out) >= cap:
            break
    return out


# ---------- assemble structured model ----------

def gather(state: State) -> tuple[list[Row], dict, list[tuple[str, str, str]]]:
    s7, l7 = gauge_c7()
    s4, l4 = gauge_c4(state)
    s8, l8 = gauge_c8()
    s10, l10 = gauge_c10()
    s9, l9 = gauge_c9()
    s2, n2, b2 = recent_by_catalyst(state, "c2")
    s1, n1, b1 = recent_by_catalyst(state, "c1")
    s6, n6, b6 = recent_by_catalyst(state, "c6")
    s3, n3, b3 = recent_by_catalyst(state, "c3")
    s5, n5, b5 = recent_by_catalyst(state, "c5")

    rows = [
        Row("C7", "Credit Market Stress", "FUSES", s7, l7),
        Row("C2", "Neocloud Distress", "FUSES", s2,
            [f"{n2} alert(s) in 7d" + (f" ({b2})" if b2 else "") + f" · watching {'/'.join(NEOCLOUDS)}"]),
        Row("C4", "Hyperscaler Capex/OCF", "HARD DATA", s4, l4),
        Row("C1", "GPU Depreciation", "HARD DATA", s1,
            [f"{n1} useful-life/impairment filing(s) in 7d" + (f" ({b1})" if b1 else "")]),
        Row("C8", "Macro / CPI+PCE", "BACKGROUND", s8, l8),
        Row("C10", "Liquidity (USD/real yield)", "BACKGROUND", s10, l10),
        Row("C6", "Memory/Storage", "BACKGROUND", s6,
            [f"{n6} price alert(s) in 7d" + (f" ({b6})" if b6 else "")]),
        Row("C3", "OpenAI Stress", "LAGGING", s3,
            [f"{n3} in 7d" + (f" ({b3})" if b3 else "") + " — mostly IPO chatter"]),
        Row("C5", "Grid Bottlenecks", "LAGGING", s5, [f"{n5} alert(s) in 7d"]),
        Row("C9", "Crypto Cycle Top", "LAGGING", s9, l9),
    ]
    counts = {st: sum(1 for r in rows if r.status == st) for st in (FIRING, WATCH, QUIET)}
    return rows, counts, notable_high_plus(state)


# ---------- FOCUS analysis (LLM with rule-based fallback) ----------

_FOCUS_PROMPT = (
    "You are the analyst behind an AI-infrastructure \"bubble-stress\" tracker. "
    "The ten signals, priority-ordered (fuses first): C7 credit spreads, C2 neocloud distress, "
    "C4 hyperscaler capex/OCF, C1 GPU depreciation, C8 CPI/PCE/Fed, C10 USD & real-yield liquidity, "
    "C6 memory prices, C3 OpenAI, C5 grid, C9 BTC cycle.\nToday's readings:\n__STATE__\n\n"
    "Recent FOCUS titles, newest first (the reader has already seen these):\n__HISTORY__\n\n"
    "Write the daily FOCUS note: pick the SINGLE most important thing today. Do NOT retell the "
    "angle of a recent title — if the readings are materially unchanged, lead with what CHANGED "
    "since the last note (cite the delta, however small) or take a signal/cross-connection the "
    "recent titles have not covered; re-lead the same story only if it actually moved today. "
    "Explain it specifically (cite the exact numbers), connect it across signals, and say what "
    "would confirm or escalate it. Direct, no hedging, no filler, no marketing. Reader is bilingual.\n"
    "Output ONLY a JSON object: {\"title\": \"<=70 chars\", \"en\": \"2-4 sentences\", \"zh\": \"2-4 句中文\"}."
)

# FOCUS-title history (repeat guard): the LLM has no memory across daily runs,
# so without this it re-picks the same standing story every day the state is
# flat. Titles live in the shared `seen` table under this namespace, keyed
# "YYYY-MM-DD|title".
FOCUS_HISTORY_TABLE = "focus_history"
FOCUS_HISTORY_LIMIT = 5


def _recent_focus_titles(state: State, limit: int = FOCUS_HISTORY_LIMIT) -> list[str]:
    """Last `limit` recorded FOCUS titles as "YYYY-MM-DD: title", newest first."""
    with state.connection() as c:
        rows = c.execute(
            "SELECT key FROM seen WHERE table_name=? ORDER BY ts DESC, key DESC LIMIT ?",
            (FOCUS_HISTORY_TABLE, limit),
        ).fetchall()
    out = []
    for (key,) in rows:
        date, _, title = key.partition("|")
        out.append(f"{date}: {title}")
    return out


def _record_focus(state: State, today: str, title: str) -> None:
    state.mark_seen(FOCUS_HISTORY_TABLE, f"{today}|{title[:120]}")


def _state_summary(rows: list[Row], notable: list[tuple[str, str, str]]) -> str:
    lines = [f"{r.id} {r.name}: {r.status} — {'; '.join(r.lines)}" for r in rows]
    if notable:
        lines.append("Notable HIGH+: " + " | ".join(f"[{c}-{s}] {t}" for c, s, t in notable[:6]))
    else:
        lines.append("Notable HIGH+: none")
    return "\n".join(lines)


def _parse_focus(raw: str) -> dict | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    sub = raw[start:end + 1]
    try:
        obj = json.loads(sub)
    except json.JSONDecodeError:
        # Tolerate an unescaped `"` inside a value (Sonnet occasionally uses
        # a straight quote as a Chinese quotation mark, which breaks strict
        # JSON parsing with no recovery otherwise).
        obj = llm.lenient_json_fields(sub, ["title", "en", "zh"])
    title, en = obj.get("title"), obj.get("en")
    if not isinstance(title, str) or not isinstance(en, str) or len(en) < 20:
        return None
    zh = obj.get("zh") if isinstance(obj.get("zh"), str) else None
    return {"title": title.strip(), "en": en.strip(), "zh": (zh or "").strip() or None}


# Standing analytical read per signal (the "so what"), woven into the FOCUS
# alongside the live numbers. Bilingual (en, zh).
_ANALYSIS = {
    "C7": ("Credit spreads are the lead fuse — bubbles break here before equities. Pinned near record-tight means the market is pricing almost no AI-credit risk; nothing to act on until they widen.",
           "信用利差是头号引信——泡沫先从这里断，早于股价。紧贴历史低位说明市场几乎没给 AI 信用风险定价；在它走阔之前无需行动。"),
    "C2": ("Neoclouds are where the first corporate crack shows — most leveraged, most customer-concentrated. A going-concern or distress 8-K here is a direct fuse, not a thermometer.",
           "Neocloud 是第一道企业裂缝出现的地方——杠杆最高、客户最集中。这里一旦出现持续经营存疑或困境 8-K，是直接引信而非温度计。"),
    "C4": ("Capex now runs ahead of all operating cash, funded by debt. Oracle is the standout — the exact name Leopold Aschenbrenner is shorting and whose 5y CDS spiked ~310% to a 16-year high. The tell: whether credit (C7) starts repricing what Oracle's balance sheet already shows.",
           "资本开支已超过全部经营现金，靠举债填。Oracle 是最突出的一个——正是 Leopold 做空、5 年期 CDS 飙约 310% 至 16 年新高的那家。关键看点：信用市场（C7）会不会开始为 Oracle 资产负债表早已显示的压力重新定价。"),
    "C1": ("Useful-life shortening / impairment is the hardest-to-argue admission that the hardware isn't paying back — a real-money write-down, not a narrative.",
           "缩短折旧年限／减值是最难被辩解掉的承认：硬件没回本——真金白银的减记，不是叙事。"),
    "C8": ("Hot CPI keeps money expensive: the Fed can't cut, which squeezes every leveraged AI bet at once. It's the macro master-condition, not an AI-specific crack — but it's the fuel line for all of them.",
           "高 CPI 让钱一直贵：美联储不能降息，同时挤压所有高杠杆 AI 押注。它是宏观总条件、不是 AI 内部裂缝，但却是所有押注的燃料管线。"),
    "C6": ("Memory price moves lead capex cuts by 1-2 quarters. Right now it's all froth (surges/shortages), no reversal — the leading indicator hasn't turned yet.",
           "存储价格领先 capex 砍单 1–2 个季度。现在全是亢奋（涨价/缺货），还没出现反转——这个领先指标尚未掉头。"),
    "C3": ("OpenAI is the demand anchor, but its signal is buried under daily IPO chatter — only HIGH+ here is actionable; MED is noise.",
           "OpenAI 是需求总锚，但信号被每日 IPO 噪音淹没——这里只有 HIGH+ 值得行动，MED 是噪音。"),
    "C5": ("Grid is the slowest-moving constraint — a ceiling on growth, not a financial fuse.",
           "电网是最慢的约束——是增长天花板，不是金融引信。"),
    "C9": ("BTC is a cross-asset risk-appetite read on the same cheap-money liquidity. In the value zone now — far from a froth/top signal.",
           "BTC 是对同一便宜钱流动性的跨资产风险偏好读数。现在在价值区——离亢奋/见顶信号还很远。"),
    "C10": ("The USD/real-yield channel is how tightening actually transmits — conditions can squeeze leveraged AI bets even with the Fed on hold. The cross-asset complement to C7 (credit) and C8 (inflation).",
            "美元/实际利率是收紧真正传导的通道——即便美联储按兵不动，金融条件也能挤压高杠杆 AI 押注。它是 C7（信用）与 C8（通胀）的跨资产补充。"),
}


def _analytical_focus(rows: list[Row]) -> dict:
    firing = [r for r in rows if r.status == FIRING]
    watch = [r for r in rows if r.status == WATCH]
    by_id = {r.id: r for r in rows}
    c7 = by_id["C7"]
    c7_cross = (f" Lead fuse C7 is still {c7.status} ({c7.lines[0]})." if c7.lines else "")
    c7_cross_zh = (f" 头号引信 C7 仍为{ {FIRING:'触发',WATCH:'观察',QUIET:'平静'}[c7.status] }（{c7.lines[0]}）。" if c7.lines else "")

    if firing:
        pick = firing[0]  # highest priority firing (rows are priority-ordered)
        # lines[0] goes in the title; the body carries only the remaining lines
        # so the two don't read as a duplicated sentence in the email.
        rest = "; ".join(pick.lines[1:])
        detail = f"{rest}. " if rest else ""
        en_a, zh_a = _ANALYSIS.get(pick.id, ("", ""))
        also = [r.id for r in firing[1:]]
        also_en = f" Also firing: {', '.join(also)}." if also else ""
        also_zh = f" 另在响：{', '.join(also)}。" if also else ""
        title = f"{pick.id} {pick.name} firing — {pick.lines[0]}"
        en = f"{detail}{en_a}{also_en}{'' if pick.id=='C7' else c7_cross}"
        zh = f"{detail}{zh_a}{also_zh}{'' if pick.id=='C7' else c7_cross_zh}"
    elif watch:
        pick = watch[0]
        en_a, zh_a = _ANALYSIS.get(pick.id, ("", ""))
        title = f"No fuse lit · closest: {pick.id} {pick.name}"
        en = f"No fuse is firing today. Closest to action: {pick.id} — {'; '.join(pick.lines)}. {en_a}{c7_cross}"
        zh = f"今日无引信触发。最接近的是 {pick.id}：{'; '.join(pick.lines)}。{zh_a}{c7_cross_zh}"
    else:
        en_a, zh_a = _ANALYSIS["C7"]
        title = "All quiet — fuses cold"
        en = f"All ten signals quiet.{c7_cross} {en_a}"
        zh = f"十个信号全部平静。{c7_cross_zh}{zh_a}"
    return {"title": title[:70], "en": en.strip(), "zh": zh.strip()}


def _focus_timeout() -> int:
    """Seconds allowed for the FOCUS LLM call. The Opus call on the full
    cross-signal prompt takes ~30s, so the blanket CATALYST_LLM_TIMEOUT
    (tuned for the shorter per-alert calls) is too tight here."""
    try:
        return int(os.environ.get("CATALYST_FOCUS_TIMEOUT", "120"))
    except ValueError:
        return 120


def generate_focus(rows: list[Row], notable: list[tuple[str, str, str]],
                   history: list[str] | None = None) -> dict:
    """LLM-written FOCUS when the claude CLI is available; otherwise a
    rule-based analytical read that bakes in the standing cross-signal thesis.
    `history` is recent FOCUS titles (newest first) so the model doesn't
    re-lead yesterday's angle when the state is flat."""
    fallback = _analytical_focus(rows)
    try:
        prompt = (_FOCUS_PROMPT
                  .replace("__STATE__", _state_summary(rows, notable))
                  .replace("__HISTORY__", "\n".join(history) if history else "(none)"))
        # Inject the full cross-signal ai-infra corpus (the FOCUS is cross-signal).
        facts = knowledge.facts_for_prompt(limit=20)
        if facts:
            prompt = f"{prompt}\n\n{facts}"
        raw = llm.freeform(prompt, timeout=_focus_timeout())
    except Exception:
        raw = None
    focus = _parse_focus(raw) if raw else None
    print(f"focus source={'llm' if focus else 'fallback'}")
    return focus or fallback


# ---------- rendering ----------

def render_text(rows: list[Row], counts: dict, notable, focus: dict, today: str,
                plan: dict | None = None) -> str:
    L = [f"catalyst-tracker — Daily Digest · {today}", "=" * 46,
         f"Status: 🔴 {counts[FIRING]} firing · 🟡 {counts[WATCH]} watch · 🟢 {counts[QUIET]} quiet",
         f"Dashboard: {DASHBOARD}", "",
         "★ FOCUS — " + focus["title"], focus["en"]]
    if focus.get("zh"):
        L.append(focus["zh"])
    L.append("")
    if plan:
        L.append(regime_signal.render_text(plan))
        L.append("")
    for tier, subtitle in TIERS:
        L.append(f"── {tier} ({subtitle}) ──")
        for r in [r for r in rows if r.tier == tier]:
            L.append(f"  {_DOT[r.status]} {r.id} {r.name} — {r.status}")
            L.extend(f"      {ln}" for ln in r.lines)
        L.append("")
    L.append("── Notable (HIGH+) last 7d ──")
    L.extend([f"  [{c}-{s}] {t}" for c, s, t in notable] if notable else ["  (none)"])
    L.append("")
    L.append("Priority: C7→C2→C4→C1→C8→C10→C6→C3→C5→C9 (fuses → hard data → background → lagging)")
    return "\n".join(L)


def _esc(s: str) -> str:
    return html.escape(s, quote=False)


def render_html(rows: list[Row], counts: dict, notable, focus: dict, today: str,
                plan: dict | None = None) -> str:
    def pill(status, n, dot):
        return (f'<span style="display:inline-block;padding:4px 12px;border-radius:14px;'
                f'background:{_COLOR[status]};color:#fff;font-size:12px;font-weight:600;'
                f'margin-right:6px;">{dot} {n} {status.lower()}</span>')

    def badge(status):
        return (f'<span style="display:inline-block;padding:2px 9px;border-radius:10px;'
                f'background:{_COLOR[status]};color:#fff;font-size:11px;font-weight:700;'
                f'letter-spacing:.3px;">{status.upper()}</span>')

    def cat_card(r: Row):
        sub = "".join(
            f'<div style="color:#566;font-size:12.5px;line-height:1.5;margin-top:2px;">{_esc(ln)}</div>'
            for ln in r.lines)
        return (
            f'<tr><td style="padding:10px 14px;border-bottom:1px solid #eef0f2;">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;">'
            f'<div style="font-size:14px;color:#1a2230;font-weight:600;">'
            f'<span style="color:#8a94a6;font-weight:700;">{r.id}</span>&nbsp; {_esc(r.name)}</div>'
            f'<div>{badge(r.status)}</div></div>{sub}</td></tr>'
        )

    tier_blocks = []
    for tier, subtitle in TIERS:
        cards = "".join(cat_card(r) for r in rows if r.tier == tier)
        tier_blocks.append(
            f'<div style="margin:18px 0 6px;font-size:11px;font-weight:700;letter-spacing:1.2px;'
            f'color:#8a94a6;text-transform:uppercase;">{tier} '
            f'<span style="font-weight:500;text-transform:none;letter-spacing:0;">· {subtitle}</span></div>'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #eef0f2;'
            f'border-radius:10px;overflow:hidden;">{cards}</table>')

    if notable:
        sev_color = {"CRITICAL": "#c0392b", "HIGH": "#e67e22"}
        notable_html = "".join(
            f'<div style="padding:7px 0;border-bottom:1px solid #f0f0f2;font-size:13px;color:#2a2f3a;">'
            f'<span style="display:inline-block;min-width:42px;padding:1px 7px;border-radius:8px;'
            f'background:{sev_color.get(s,"#888")};color:#fff;font-size:10px;font-weight:700;margin-right:8px;">{s}</span>'
            f'<b style="color:#8a94a6;">{c}</b>&nbsp; {_esc(t)}</div>'
            for c, s, t in notable)
    else:
        notable_html = '<div style="color:#7a8;font-size:13px;padding:6px 0;">✓ none — no HIGH/CRITICAL signals in the last 7 days</div>'

    focus_zh = (f'<div style="font-size:13.5px;line-height:1.7;color:#3a4658;margin-top:8px;">{_esc(focus["zh"])}</div>'
                if focus.get("zh") else "")

    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f4f5f7;">
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:640px;margin:0 auto;padding:20px 14px;">

  <div style="background:#0f1729;border-radius:12px 12px 0 0;padding:20px 22px;">
    <div style="color:#fff;font-size:19px;font-weight:700;letter-spacing:.2px;">catalyst-tracker</div>
    <div style="color:#7f8aa0;font-size:13px;margin-top:2px;">AI bubble-stress · Daily Digest · {today}</div>
    <div style="margin-top:14px;">{pill(FIRING,counts[FIRING],'🔴')}{pill(WATCH,counts[WATCH],'🟡')}{pill(QUIET,counts[QUIET],'🟢')}</div>
  </div>

  <div style="background:#fff7ed;border-left:4px solid #e67e22;border-radius:0 0 0 0;padding:16px 22px;">
    <div style="font-size:11px;font-weight:700;letter-spacing:1.5px;color:#e67e22;">★ FOCUS · 今日重点</div>
    <div style="font-size:16px;font-weight:700;color:#1a2230;margin:6px 0;">{_esc(focus["title"])}</div>
    <div style="font-size:13.5px;line-height:1.7;color:#2a3344;">{_esc(focus["en"])}</div>
    {focus_zh}
  </div>
{regime_signal.render_html_card(plan)}
  <div style="background:#f4f5f7;padding:4px 8px 10px;">
    {''.join(tier_blocks)}

    <div style="margin:20px 0 6px;font-size:11px;font-weight:700;letter-spacing:1.2px;color:#8a94a6;text-transform:uppercase;">Notable · HIGH+ last 7d</div>
    <div style="background:#fff;border:1px solid #eef0f2;border-radius:10px;padding:6px 16px;">{notable_html}</div>
  </div>

  <div style="text-align:center;padding:14px;color:#9aa3b2;font-size:12px;">
    <a href="{DASHBOARD}" style="color:#3b7ddd;text-decoration:none;font-weight:600;">Open dashboard →</a>
    <div style="margin-top:6px;">Priority C7→C2→C4→C1→C8→C10→C6→C3→C5→C9 · fuses → hard data → background → lagging</div>
  </div>
</div></body></html>"""


# ---------- compose + send ----------

def build(record_focus: bool = True) -> tuple[str, str, str]:
    state = State("daily_report")
    today = dt.date.today().isoformat()
    rows, counts, notable = gather(state)
    focus = generate_focus(rows, notable, history=_recent_focus_titles(state))
    if record_focus:
        _record_focus(state, today, focus["title"])
    try:
        plan = regime_signal.plan_from_rows(rows)
    except Exception:
        plan = None
    subject = f"[catalyst-tracker] {today} · 🔴{counts[FIRING]} 🟡{counts[WATCH]} 🟢{counts[QUIET]} · {focus['title'][:50]}"
    text = render_text(rows, counts, notable, focus, today, plan)
    html_body = render_html(rows, counts, notable, focus, today, plan)
    return subject, text, html_body


def send(subject: str, text: str, html_body: str) -> None:
    send_email(subject, text=text, html=html_body)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="catalyst-tracker daily digest")
    p.add_argument("--dry-run", action="store_true", help="print text body to stdout")
    p.add_argument("--html-out", metavar="PATH", help="also write the HTML body to a file")
    args = p.parse_args(argv)
    subject, text, html_body = build(record_focus=not args.dry_run)
    if args.html_out:
        Path(args.html_out).write_text(html_body)
    if args.dry_run:
        print(subject)
        print(text)
    else:
        send(subject, text, html_body)
        print("daily digest sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Render docs/index.html and docs/data/status.json from state/tracker.sqlite."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jinja2 import Environment, select_autoescape

from lib.state import State
from lib.thresholds import all_thresholds

_JINJA_ENV = Environment(autoescape=select_autoescape(["html", "htm", "xml"]))

REPO = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO / "docs" / "index.html.j2"
OUT_HTML = REPO / "docs" / "index.html"
OUT_JSON = REPO / "docs" / "data" / "status.json"
OUT_THRESHOLDS = REPO / "docs" / "thresholds.html"

CATALYSTS = [
    ("C1", "GPU Depreciation Useful-Life Changes"),
    ("C2", "Neocloud Distress"),
    ("C3", "OpenAI Financial Stress"),
    ("C4", "Hyperscaler Capex Cuts"),
    ("C5", "Grid Bottlenecks"),
    ("C6", "Memory/Storage Price Stress"),
    ("C7", "Credit Market Stress"),
    ("C8", "Macro Triggers"),
    ("C9", "Crypto Cycle Top"),
    ("C10", "Liquidity Tightening (USD / Real Yields)"),
    ("C11", "SpaceX IPO Unlock / Passive Flows"),
]


def collect_status() -> dict:
    st = State("dashboard")
    counts: dict[str, dict] = {}
    with st.connection() as c:
        rows = c.execute(
            "SELECT table_name, COUNT(*), MAX(ts) FROM seen GROUP BY table_name"
        ).fetchall()
    last_ts = 0
    table_counts = {}
    for table, cnt, ts in rows:
        ts_int = int(ts or 0)
        last_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts_int)) if ts_int else ""
        table_counts[table] = {"count": int(cnt), "last_ts": ts_int, "last_str": last_str}
        if ts_int > last_ts:
            last_ts = ts_int

    # Snapshot of c4 ratios and c5 queues if those tables exist.
    c4_rows = []
    c5_rows = []
    try:
        with st.connection() as c:
            c4_rows = c.execute(
                "SELECT cik, period_end, capex_ttm, ocf_ttm, ratio FROM c4_xbrl ORDER BY period_end DESC LIMIT 20"
            ).fetchall()
    except Exception:
        pass
    try:
        with st.connection() as c:
            c5_rows = c.execute(
                "SELECT iso, snapshot_date, total_mw, count, withdrawn_count FROM c5_queues ORDER BY snapshot_date DESC LIMIT 20"
            ).fetchall()
    except Exception:
        pass

    alerts_rows = []
    try:
        with st.connection() as c:
            alerts_rows = c.execute(
                "SELECT id, ts, catalyst, severity, subject, body, emailed "
                "FROM alerts ORDER BY ts DESC LIMIT 200"
            ).fetchall()
    except Exception:
        pass

    # U100/NDX buy plan. Fuse state (A vs B) is derived cheaply from recent
    # C7/C2 HIGH+ alerts rather than re-fetching the credit series on every
    # dashboard rebuild; the drawdown ladder needs one keyless FRED fetch.
    plan = None
    try:
        from scripts.regime_signal import build_plan
        from lib.index_quote import ndx_drawdown
        since = int(time.time()) - 7 * 86400
        with st.connection() as c:
            fuse_rows = c.execute(
                "SELECT DISTINCT UPPER(catalyst) FROM alerts WHERE ts>=? "
                "AND severity IN ('HIGH','CRITICAL') AND LOWER(catalyst) IN ('c7','c2')",
                (since,),
            ).fetchall()
        fuses = sorted({r[0] for r in fuse_rows})
        plan = build_plan(ndx_drawdown(), bool(fuses), fuses)
    except Exception:
        plan = None

    return {
        "generated_at": int(time.time()),
        "generated_at_str": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "last_event_ts": last_ts,
        "tables": table_counts,
        "c4_xbrl": [
            {"cik": r[0], "period_end": r[1], "capex_ttm": r[2], "ocf_ttm": r[3], "ratio": r[4]}
            for r in c4_rows
        ],
        "c5_queues": [
            {"iso": r[0], "snapshot_date": r[1], "total_mw": r[2], "count": r[3], "withdrawn_count": r[4]}
            for r in c5_rows
        ],
        "alerts": [
            {
                "id": r[0],
                "ts": int(r[1]),
                "ts_str": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(r[1]))),
                "catalyst": (r[2] or "").upper(),
                "severity": r[3],
                "subject": r[4],
                "body": r[5],
                "emailed": bool(r[6]),
            }
            for r in alerts_rows
        ],
        "catalysts": [{"id": cid, "name": name} for cid, name in CATALYSTS],
        "plan": plan,
    }


def render(status: dict) -> str:
    if TEMPLATE_PATH.exists():
        tmpl = _JINJA_ENV.from_string(TEMPLATE_PATH.read_text())
    else:
        tmpl = _JINJA_ENV.from_string(DEFAULT_TEMPLATE)
    return tmpl.render(s=status)


DEFAULT_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>catalyst-tracker</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }
  h1 { margin-bottom: 0; }
  .meta { color: #666; font-size: 0.9em; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border-bottom: 1px solid #ddd; padding: 6px 10px; text-align: left; }
  th { background: #f6f6f6; }
  code { background: #f0f0f0; padding: 0 4px; border-radius: 3px; }
  .alert-toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 0.5rem 0 1rem; font-size: 0.9em; }
  .alert-toolbar select, .alert-toolbar button { font-size: 0.9em; padding: 2px 6px; }
  .alert { border-bottom: 1px solid #eee; padding: 6px 0; }
  .alert summary { cursor: pointer; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .alert summary .subj { flex: 1; min-width: 200px; }
  .alert pre { background: #f6f6f6; padding: 8px; border-radius: 4px; white-space: pre-wrap; word-break: break-word; }
  .alert.read summary { color: #999; }
  .alert.read summary .subj { font-weight: normal; }
  .sev { display: inline-block; padding: 1px 8px; border-radius: 10px; color: white; font-size: 0.72em; font-weight: 600; letter-spacing: 0.5px; }
  .sev-bg-CRITICAL { background: #c0392b; }
  .sev-bg-HIGH     { background: #e67e22; }
  .sev-bg-MED      { background: #f1c40f; color: #333; }
  .sev-bg-LOG      { background: #7f8c8d; }
  .plan { border: 1px solid #e0e0e0; border-radius: 8px; padding: 14px 18px; margin: 1.2rem 0; background: #fafbfc; }
  .plan .ttl { font-size: 0.72em; font-weight: 700; letter-spacing: 1.2px; }
  .plan .lvl { font-size: 1.15em; font-weight: 600; color: #1a2230; margin: 4px 0; }
  .plan .reg { font-weight: 600; }
  .plan table { margin: 8px 0 0; }
  .plan td { border: none; padding: 4px 8px; font-size: 0.92em; }
  .plan .pct { text-align: right; font-weight: 600; }
  .plan .at { text-align: right; color: #667; font-variant-numeric: tabular-nums; }
  .plan tr.on { background: #eef9f0; }
  .plan tr.next { background: #fff7ed; }
  .plan .warn { color: #c0392b; font-size: 0.9em; margin-top: 8px; }
  .regA { color: #27ae60; } .regA-b { border-left: 4px solid #27ae60; }
  .regB { color: #c0392b; } .regB-b { border-left: 4px solid #c0392b; }
</style>
</head><body>
<h1>catalyst-tracker</h1>
<div class="meta">Generated {{ s.generated_at_str }} · <a href="thresholds.html">view thresholds →</a></div>

{% if s.plan %}
{% set p = s.plan %}
<div class="plan reg{{ p.regime }}-b">
  <div class="ttl reg{{ p.regime }}">★ BUY PLAN · U100 / NDX</div>
  <div class="lvl">NDX {{ '{:,.0f}'.format(p.ndx.current) }} · drawdown {{ '%+.1f'|format(p.ndx.drawdown*100) }}% off ATH {{ '{:,.0f}'.format(p.ndx.ath) }}</div>
  <div class="reg reg{{ p.regime }}">Regime {{ p.regime }}{% if p.fuses %} · lit: {{ p.fuses|join(', ') }}{% else %} · 引信未响{% endif %}
    · target {{ p.cumulative_target }}% deployed{% if p.reserve %} · reserve {{ p.reserve }}%{% endif %}</div>
  <table>
  {% for r in p.rungs %}
    <tr class="{% if r.triggered %}on{% elif p.next_rung and r.thresh == p.next_rung.thresh %}next{% endif %}">
      <td>{% if r.triggered %}✅{% elif p.next_rung and r.thresh == p.next_rung.thresh %}➡️{% else %}⬜{% endif %}
        <b>{{ '%.0f'|format(r.thresh*100) }}%</b> · {{ r.label }}</td>
      <td class="pct">{{ r.pct }}%</td>
      <td class="at">NDX {{ '{:,.0f}'.format(r.level) }}</td>
    </tr>
  {% endfor %}
  </table>
  {% if p.regime == 'B' %}<div class="warn">⚠ Fast ladder frozen — deep rung needs stabilisation (C7 stops widening, or 4–6wk no new 20d-low).</div>{% endif %}
  <div class="meta" style="margin-top:8px;">Only the C7/C2 fuses switch Regime A↔B; the other signals are thermometers. Tracks <a href="https://www.globalxetfs.com.au/funds/u100/">ASX:U100</a> (Nasdaq-100).</div>
</div>
{% endif %}

<h2>Catalysts</h2>
<table>
<tr><th>ID</th><th>Name</th></tr>
{% for cat in s.catalysts %}
<tr><td><code>{{ cat.id }}</code></td><td>{{ cat.name }}</td></tr>
{% endfor %}
</table>

<h2>Recent alerts <span id="alerts-count" class="meta"></span></h2>
<div class="alert-toolbar">
  <label>Catalyst:
    <select id="filter-catalyst">
      <option value="">all</option>
      <option value="C1">C1</option><option value="C2">C2</option>
      <option value="C3">C3</option><option value="C4">C4</option>
      <option value="C5">C5</option><option value="C6">C6</option>
      <option value="C7">C7</option><option value="C8">C8</option>
      <option value="C9">C9</option><option value="C10">C10</option>
    </select>
  </label>
  <label>Severity:
    <select id="filter-severity">
      <option value="">all</option>
      <option value="CRITICAL">CRITICAL</option>
      <option value="HIGH">HIGH</option>
      <option value="MED">MED</option>
      <option value="LOG">LOG</option>
    </select>
  </label>
  <label><input type="checkbox" id="filter-unread"> only unread</label>
  <button id="mark-all-read" type="button">mark all visible read</button>
  <button id="clear-read" type="button">reset read state</button>
</div>
<div id="alerts-list">
{% for a in s.alerts %}
<details class="alert sev-{{ a.severity }}" data-id="{{ a.id }}" data-catalyst="{{ a.catalyst }}" data-severity="{{ a.severity }}">
  <summary>
    <span class="sev sev-bg-{{ a.severity }}">{{ a.severity }}</span>
    <code>{{ a.catalyst }}</code>
    <span class="subj">{{ a.subject }}</span>
    <span class="meta">{{ a.ts_str }}{% if not a.emailed %} · muted{% endif %}</span>
  </summary>
  <pre>{{ a.body }}</pre>
  <button class="mark-read" type="button" data-id="{{ a.id }}">mark read</button>
</details>
{% else %}
<p class="meta">No alerts recorded yet.</p>
{% endfor %}
</div>

<h2>State table counts</h2>
<table>
<tr><th>Table</th><th>Rows</th><th>Last event (UTC)</th></tr>
{% for name, info in s.tables.items()|sort %}
<tr><td><code>{{ name }}</code></td><td>{{ info.count }}</td>
<td>{% if info.last_str %}{{ info.last_str }}{% else %}—{% endif %}</td></tr>
{% endfor %}
</table>

{% if s.c4_xbrl %}
<h2>C4 — TTM Capex/OCF (most recent 20)</h2>
<table>
<tr><th>CIK</th><th>Period end</th><th>Capex TTM ($B)</th><th>OCF TTM ($B)</th><th>Ratio</th></tr>
{% for r in s.c4_xbrl %}
<tr>
<td>{{ r.cik }}</td><td>{{ r.period_end }}</td>
<td>{{ '%.2f'|format(r.capex_ttm/1e9) }}</td>
<td>{{ '%.2f'|format(r.ocf_ttm/1e9) }}</td>
<td>{{ '%.1f%%'|format(r.ratio*100) }}</td>
</tr>
{% endfor %}
</table>
{% endif %}

{% if s.c5_queues %}
<h2>C5 — ISO queue snapshots</h2>
<table>
<tr><th>ISO</th><th>Snapshot</th><th>Total MW</th><th>Count</th><th>Withdrawn</th></tr>
{% for r in s.c5_queues %}
<tr>
<td>{{ r.iso }}</td><td>{{ r.snapshot_date }}</td>
<td>{{ '%.0f'|format(r.total_mw) }}</td>
<td>{{ r.count }}</td><td>{{ r.withdrawn_count }}</td>
</tr>
{% endfor %}
</table>
{% endif %}

<hr>
<p class="meta">Source: <a href="https://github.com/cyprien0312/catalyst-tracker">catalyst-tracker</a></p>
<script>
(function () {
  const KEY = "catalyst-tracker:read-ids";
  const read = new Set(JSON.parse(localStorage.getItem(KEY) || "[]"));
  const list = document.getElementById("alerts-list");
  const fCat = document.getElementById("filter-catalyst");
  const fSev = document.getElementById("filter-severity");
  const fUnread = document.getElementById("filter-unread");
  const count = document.getElementById("alerts-count");

  function persist() { localStorage.setItem(KEY, JSON.stringify([...read])); }

  function applyState() {
    let visible = 0;
    for (const el of list.querySelectorAll(".alert")) {
      const id = el.dataset.id;
      const isRead = read.has(id);
      el.classList.toggle("read", isRead);
      const catOK = !fCat.value || el.dataset.catalyst === fCat.value;
      const sevOK = !fSev.value || el.dataset.severity === fSev.value;
      const unreadOK = !fUnread.checked || !isRead;
      const show = catOK && sevOK && unreadOK;
      el.style.display = show ? "" : "none";
      if (show) visible++;
    }
    count.textContent = "(" + visible + " visible)";
  }

  list.addEventListener("click", (e) => {
    const btn = e.target.closest(".mark-read");
    if (!btn) return;
    e.preventDefault();
    read.add(btn.dataset.id);
    persist();
    applyState();
  });

  document.getElementById("mark-all-read").addEventListener("click", () => {
    for (const el of list.querySelectorAll(".alert")) {
      if (el.style.display !== "none") read.add(el.dataset.id);
    }
    persist();
    applyState();
  });

  document.getElementById("clear-read").addEventListener("click", () => {
    if (!confirm("Reset read state on this device?")) return;
    read.clear();
    persist();
    applyState();
  });

  fCat.addEventListener("change", applyState);
  fSev.addEventListener("change", applyState);
  fUnread.addEventListener("change", applyState);
  applyState();
})();
</script>
</body></html>
"""


_SEVERITY_COLORS = {
    "CRITICAL": "#c0392b",
    "HIGH": "#e67e22",
    "MED": "#f1c40f",
    "LOG": "#7f8c8d",
    "—": "#bdc3c7",
}


def render_thresholds() -> str:
    thresholds = all_thresholds()
    by_cat: dict[str, list] = {}
    for t in thresholds:
        by_cat.setdefault(t.catalyst, []).append(t)
    tmpl = _JINJA_ENV.from_string(THRESHOLDS_TEMPLATE)
    return tmpl.render(by_cat=by_cat,
                       cat_names=dict(CATALYSTS),
                       colors=_SEVERITY_COLORS,
                       generated_at_str=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))


THRESHOLDS_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>catalyst-tracker — thresholds</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }
  h1 { margin-bottom: 0; }
  h2 { margin-top: 2rem; padding-bottom: 4px; border-bottom: 2px solid #eee; }
  .meta { color: #666; font-size: 0.9em; }
  .card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin: 1rem 0; }
  .card { border: 1px solid #e0e0e0; border-radius: 6px; padding: 10px 14px; background: #fafafa; }
  .card .name { font-weight: 600; color: #222; }
  .card .val { font-family: ui-monospace, monospace; font-size: 1.05em; margin: 4px 0; color: #111; word-break: break-word; }
  .card .note { color: #666; font-size: 0.85em; margin-top: 4px; }
  .sev { display: inline-block; padding: 1px 8px; border-radius: 10px; color: white; font-size: 0.75em; font-weight: 600; letter-spacing: 0.5px; }
</style>
</head><body>
<h1>Thresholds</h1>
<div class="meta">Generated {{ generated_at_str }} · <a href="index.html">← dashboard</a></div>

<p>The numbers and patterns each catalyst uses to decide when to fire an alert.
Edit <code>lib/thresholds.py</code> (or the catalyst module) and push to tune them.</p>

{% for cid in ["C1","C2","C3","C4","C5","C6","C7","C8","C9","C10"] %}
{% set items = by_cat.get(cid, []) %}
{% if items %}
<h2>{{ cid }} — {{ cat_names.get(cid, "") }}</h2>
<div class="card-grid">
  {% for t in items %}
  <div class="card">
    <div class="name">{{ t.name }}</div>
    <div class="val">{{ t.value }}</div>
    <div>
      <span class="sev" style="background: {{ colors.get(t.severity, '#888') }};">{{ t.severity }}</span>
    </div>
    {% if t.note %}<div class="note">{{ t.note }}</div>{% endif %}
  </div>
  {% endfor %}
</div>
{% endif %}
{% endfor %}

<hr>
<p class="meta">Source: <a href="https://github.com/cyprien0312/catalyst-tracker">catalyst-tracker</a></p>
</body></html>
"""


def main() -> int:
    status = collect_status()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(status, indent=2))
    OUT_HTML.write_text(render(status))
    OUT_THRESHOLDS.write_text(render_thresholds())
    print(f"wrote {OUT_HTML}, {OUT_THRESHOLDS}, {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

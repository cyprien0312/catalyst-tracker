"""Render docs/index.html and docs/data/status.json from state/tracker.sqlite."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jinja2 import Template

from lib.state import State
from lib.thresholds import all_thresholds

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
    }


def render(status: dict) -> str:
    if TEMPLATE_PATH.exists():
        tmpl = Template(TEMPLATE_PATH.read_text())
    else:
        tmpl = Template(DEFAULT_TEMPLATE)
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
</style>
</head><body>
<h1>catalyst-tracker</h1>
<div class="meta">Generated {{ s.generated_at_str }} · <a href="thresholds.html">view thresholds →</a></div>

<h2>Catalysts</h2>
<table>
<tr><th>ID</th><th>Name</th></tr>
{% for cat in s.catalysts %}
<tr><td><code>{{ cat.id }}</code></td><td>{{ cat.name }}</td></tr>
{% endfor %}
</table>

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
    tmpl = Template(THRESHOLDS_TEMPLATE)
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

{% for cid in ["C1","C2","C3","C4","C5"] %}
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

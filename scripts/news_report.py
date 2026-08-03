"""Daily news roll-up e-mail for catalyst-tracker.

The companion to `scripts/daily_report.py`. The digest answers "what is the
state of the eleven signals"; this one answers "what actually came in today",
carrying the full body + bilingual explanation of every alert from the window
so the per-alert e-mails can stay muted.

Design notes:
  - Reads the `alerts` table only — it never re-fetches feeds and never writes
    state, so it is safe to re-run and safe to run out of order with the
    catalysts themselves.
  - Includes alerts that were e-mailed instantly too (tagged `sent instantly`),
    so the report is a complete daily record rather than a "what you missed"
    list with unexplained gaps.
  - Deduped on the normalised subject, because the same headline routinely
    arrives via several Google News feeds (e.g. the "DRAM" and "NAND" queries
    both match the same article).

    python scripts/news_report.py            # send
    python scripts/news_report.py --dry-run  # print text body to stdout
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.email_send import send_email
from lib.log import get_logger
from lib.state import State
from scripts.daily_report import DASHBOARD, _norm_subject

log = get_logger(__name__)

DEFAULT_HOURS = 24

# Same priority spine as the daily digest, so the two mails read consistently.
CATALYST_ORDER = ["c7", "c2", "c4", "c1", "c8", "c10", "c6", "c3", "c5", "c9",
                  "c11", "buyplan"]
CATALYST_NAME = {
    "c1": "Depreciation", "c2": "Neoclouds", "c3": "OpenAI", "c4": "Capex",
    "c5": "Grid", "c6": "Memory", "c7": "Credit", "c8": "Macro",
    "c9": "Crypto", "c10": "Liquidity", "c11": "SpaceX unlock",
    "buyplan": "Buy plan",
}
_SEV_RANK = {"LOG": 0, "MED": 1, "HIGH": 2, "CRITICAL": 3}
_SEV_COLOR = {"CRITICAL": "#8e1b1b", "HIGH": "#c0392b",
              "MED": "#e67e22", "LOG": "#7f8c8d"}

SEPARATOR = "─" * 60


class Item:
    """One deduped alert, split into its raw head and its explanation block."""

    __slots__ = ("catalyst", "severity", "subject", "link", "detail",
                 "explanation", "emailed", "ts", "dupes")

    def __init__(self, catalyst, severity, subject, body, emailed, ts):
        self.catalyst = (catalyst or "unknown").lower()
        self.severity = severity
        self.subject = _norm_subject(subject)
        self.emailed = bool(emailed)
        self.ts = ts
        self.dupes = 1
        head, self.explanation = _split_body(body or "")
        self.link = _field(head, "Link")
        self.detail = _detail_lines(head)


def _split_body(body: str) -> tuple[str, str]:
    """Split an alert body into (head, explanation) around the rule line."""
    if SEPARATOR in body:
        head, _, tail = body.partition(SEPARATOR)
        return head.strip(), tail.strip()
    return body.strip(), ""


def _field(head: str, name: str) -> str:
    prefix = f"{name}:"
    for line in head.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _detail_lines(head: str, cap: int = 6) -> list[str]:
    """Numeric context lines (`Current: 2.47%`), minus the plumbing fields."""
    skip = ("Severity:", "Feed:", "Link:", "Published:")
    out = []
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith(skip) or line.startswith("<a href"):
            continue
        out.append(line)
        if len(out) >= cap:
            break
    return out


def collect(state: State, hours: int = DEFAULT_HOURS) -> list[Item]:
    """Deduped alerts from the window, newest first within each catalyst."""
    since = int(time.time()) - hours * 3600
    try:
        with state.connection() as c:
            rows = c.execute(
                "SELECT catalyst, severity, subject, body, emailed, ts FROM alerts "
                "WHERE ts>=? ORDER BY ts DESC",
                (since,),
            ).fetchall()
    except Exception:
        log.exception("news_report.collect failed")
        return []

    by_key: dict[tuple[str, str], Item] = {}
    for cat, sev, subject, body, emailed, ts in rows:
        item = Item(cat, sev, subject, body, emailed, ts)
        key = (item.catalyst, item.subject.lower())
        prior = by_key.get(key)
        if prior is None:
            by_key[key] = item
            continue
        # Same headline seen on another feed: keep the loudest, count the dupe.
        prior.dupes += 1
        if _SEV_RANK.get(item.severity, 1) > _SEV_RANK.get(prior.severity, 1):
            prior.severity = item.severity
        prior.emailed = prior.emailed or item.emailed
    return list(by_key.values())


def group(items: list[Item]) -> list[tuple[str, list[Item]]]:
    """Group by catalyst in digest priority order, loudest alert first."""
    buckets: dict[str, list[Item]] = {}
    for it in items:
        buckets.setdefault(it.catalyst, []).append(it)
    for bucket in buckets.values():
        bucket.sort(key=lambda i: (-_SEV_RANK.get(i.severity, 1), -i.ts))
    known = [(c, buckets.pop(c)) for c in CATALYST_ORDER if c in buckets]
    return known + sorted(buckets.items())


def counts(items: list[Item]) -> dict[str, int]:
    out = {"CRITICAL": 0, "HIGH": 0, "MED": 0, "LOG": 0}
    for it in items:
        out[it.severity] = out.get(it.severity, 0) + 1
    return out


def _headline(grouped, total: int) -> str:
    parts = [f"{cat.upper()}×{len(its)}" for cat, its in grouped[:4]]
    tail = " +" + str(len(grouped) - 4) + " more" if len(grouped) > 4 else ""
    return f"{total} items · " + ", ".join(parts) + tail if parts else "no items"


# ---------- rendering ----------

def render_text(grouped, sev, today: str, hours: int) -> str:
    total = sum(len(its) for _, its in grouped)
    L = [f"catalyst-tracker — News Roll-up · {today}", "=" * 46,
         f"Window: last {hours}h · {total} items "
         f"(🔴 {sev['CRITICAL']} crit · {sev['HIGH']} high · {sev['MED']} med)",
         f"Dashboard: {DASHBOARD}", ""]
    if not grouped:
        L.append("(no alerts in the window)")
        return "\n".join(L)
    for cat, items in grouped:
        L.append(f"── {cat.upper()} {CATALYST_NAME.get(cat, '')} ({len(items)}) ──")
        for it in items:
            flags = []
            if it.dupes > 1:
                flags.append(f"×{it.dupes} feeds")
            if it.emailed:
                flags.append("sent instantly")
            suffix = f"  [{', '.join(flags)}]" if flags else ""
            L.append(f"  [{it.severity}] {it.subject}{suffix}")
            L.extend(f"      {d}" for d in it.detail)
            if it.link:
                L.append(f"      {it.link}")
            if it.explanation:
                L.extend(f"      {ln}" for ln in it.explanation.splitlines() if ln.strip())
            L.append("")
        L.append("")
    L.append("Per-alert e-mails are muted below CRITICAL — this roll-up is the "
             "full record. Tune via CATALYST_EMAIL_MIN_SEVERITY in ~/.catalyst.env.")
    return "\n".join(L)


def _esc(s: str) -> str:
    return html.escape(s, quote=False)


def render_html(grouped, sev, today: str, hours: int) -> str:
    total = sum(len(its) for _, its in grouped)
    P = ['<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,'
         'Helvetica,Arial,sans-serif;max-width:720px;margin:0 auto;color:#222;">',
         f'<h2 style="margin:0 0 4px;">News Roll-up · {_esc(today)}</h2>',
         f'<p style="margin:0 0 16px;color:#666;font-size:13px;">Last {hours}h · '
         f'{total} items · <a href="{DASHBOARD}">dashboard</a></p>']
    for name in ("CRITICAL", "HIGH", "MED"):
        if sev.get(name):
            P.append(f'<span style="display:inline-block;padding:4px 12px;'
                     f'border-radius:14px;background:{_SEV_COLOR[name]};color:#fff;'
                     f'font-size:12px;font-weight:600;margin:0 6px 12px 0;">'
                     f'{sev[name]} {name.lower()}</span>')
    if not grouped:
        P.append('<p style="color:#666;">No alerts in the window.</p></div>')
        return "".join(P)
    for cat, items in grouped:
        P.append(f'<h3 style="margin:20px 0 8px;border-bottom:1px solid #eee;'
                 f'padding-bottom:4px;">{_esc(cat.upper())} '
                 f'<span style="color:#888;font-weight:400;font-size:14px;">'
                 f'{_esc(CATALYST_NAME.get(cat, ""))} · {len(items)}</span></h3>')
        for it in items:
            flags = []
            if it.dupes > 1:
                flags.append(f"×{it.dupes} feeds")
            if it.emailed:
                flags.append("sent instantly")
            title = _esc(it.subject)
            if it.link:
                title = f'<a href="{_esc(it.link)}" style="color:#1a4f8a;">{title}</a>'
            P.append('<div style="margin:0 0 14px;padding:10px 12px;'
                     'background:#fafafa;border-left:3px solid '
                     f'{_SEV_COLOR.get(it.severity, "#999")};">')
            P.append(f'<div style="font-weight:600;">{title}</div>')
            meta = it.severity + (" · " + ", ".join(flags) if flags else "")
            P.append(f'<div style="color:#888;font-size:12px;margin:2px 0 6px;">'
                     f'{_esc(meta)}</div>')
            for d in it.detail:
                P.append(f'<div style="font-size:13px;color:#444;">{_esc(d)}</div>')
            if it.explanation:
                P.append('<div style="font-size:13px;color:#333;margin-top:6px;'
                         'white-space:pre-wrap;">' + _esc(it.explanation) + '</div>')
            P.append('</div>')
    P.append('<p style="color:#888;font-size:12px;margin-top:24px;">Per-alert '
             'e-mails are muted below CRITICAL — this roll-up is the full record.</p>')
    P.append('</div>')
    return "".join(P)


def build(hours: int = DEFAULT_HOURS) -> tuple[str, str, str, int]:
    state = State("news_report")
    today = dt.date.today().isoformat()
    items = collect(state, hours=hours)
    grouped = group(items)
    sev = counts(items)
    subject = f"[catalyst-tracker] News · {today} · {_headline(grouped, len(items))}"
    return (subject, render_text(grouped, sev, today, hours),
            render_html(grouped, sev, today, hours), len(items))


def send(subject: str, text: str, html_body: str) -> None:
    send_email(subject, text=text, html=html_body)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="catalyst-tracker daily news roll-up")
    p.add_argument("--dry-run", action="store_true", help="print text body to stdout")
    p.add_argument("--hours", type=int, default=DEFAULT_HOURS,
                   help=f"look-back window in hours (default {DEFAULT_HOURS})")
    p.add_argument("--html-out", metavar="PATH", help="also write the HTML body to a file")
    p.add_argument("--send-empty", action="store_true",
                   help="send even when the window is empty (default: skip)")
    args = p.parse_args(argv)

    subject, text, html_body, n = build(hours=args.hours)
    if args.html_out:
        Path(args.html_out).write_text(html_body)
    if args.dry_run:
        print(subject)
        print(text)
        return 0
    if n == 0 and not args.send_empty:
        print("news roll-up: no alerts in window, nothing sent")
        return 0
    send(subject, text, html_body)
    print(f"news roll-up sent ({n} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

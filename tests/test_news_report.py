import importlib.util
import sys
import time
from pathlib import Path

from lib.state import State

# news_report.py lives in scripts/, load it as a module (same pattern as
# tests/test_daily_report.py).
_spec = importlib.util.spec_from_file_location(
    "news_report", Path(__file__).resolve().parent.parent / "scripts" / "news_report.py")
nr = importlib.util.module_from_spec(_spec)
sys.modules["news_report"] = nr
_spec.loader.exec_module(nr)

SEP = nr.SEPARATOR

BODY = (
    "Severity:  MED\n"
    "Feed:      https://news.google.com/rss/search?q=DRAM\n"
    "Published: Mon, 03 Aug 2026 22:00:36 GMT\n"
    "Link:      https://example.test/article\n"
    "\n"
    "Commodity DRAM Prices Hit Record - thelec.net\n"
    f"\n{SEP}\n"
    "What this means:\nPrices rose.\n\n内容:\n价格上涨。\n"
)


def _db(tmp_path) -> State:
    return State("test_news", db_path=tmp_path / "t.sqlite")


def _insert(st: State, *, catalyst="c6", severity="MED", subject="[C6-MED] X - src",
            body=BODY, emailed=0, age_s=60):
    with st.connection() as c:
        c.execute(
            "INSERT INTO alerts(ts, catalyst, severity, subject, body, emailed, fingerprint) "
            "VALUES (?,?,?,?,?,?,?)",
            (int(time.time()) - age_s, catalyst, severity, subject, body, emailed,
             f"fp{time.time_ns()}"),
        )


# ---------- body splitting ----------

def test_split_body_separates_explanation():
    head, expl = nr._split_body(BODY)
    assert "Severity:" in head and SEP not in head
    assert expl.startswith("What this means:") and "价格上涨" in expl


def test_split_body_without_separator_yields_empty_explanation():
    head, expl = nr._split_body("just a body")
    assert head == "just a body" and expl == ""


def test_field_and_detail_lines_drop_plumbing():
    head, _ = nr._split_body(BODY)
    assert nr._field(head, "Link") == "https://example.test/article"
    assert nr._field(head, "Nope") == ""
    detail = nr._detail_lines(head)
    assert detail == ["Commodity DRAM Prices Hit Record - thelec.net"]


# ---------- collection / dedup ----------

def test_collect_dedupes_same_headline_across_feeds(tmp_path):
    st = _db(tmp_path)
    _insert(st, subject="[C6-MED] Same headline - thelec.net")
    _insert(st, subject="[C6-MED] Same headline - thelec.net")
    items = nr.collect(st)
    assert len(items) == 1
    assert items[0].dupes == 2


def test_dedup_keeps_loudest_severity_and_emailed_flag(tmp_path):
    st = _db(tmp_path)
    _insert(st, severity="MED", emailed=0, subject="[C6-MED] Dup - a")
    _insert(st, severity="HIGH", emailed=1, subject="[C6-HIGH] Dup - a")
    (item,) = nr.collect(st)
    assert item.severity == "HIGH"
    assert item.emailed is True


def test_different_catalysts_are_not_deduped_together(tmp_path):
    st = _db(tmp_path)
    _insert(st, catalyst="c6", subject="[C6-MED] Shared - x")
    _insert(st, catalyst="c11", subject="[C11-MED] Shared - x")
    assert len(nr.collect(st)) == 2


def test_collect_respects_window(tmp_path):
    st = _db(tmp_path)
    _insert(st, subject="[C6-MED] Old - x", age_s=48 * 3600)
    _insert(st, subject="[C6-MED] New - x", age_s=60)
    items = nr.collect(st, hours=24)
    assert [i.subject for i in items] == ["New"]


def test_collect_on_missing_table_returns_empty(tmp_path):
    st = State("test_news", db_path=tmp_path / "t.sqlite")
    with st.connection() as c:
        c.execute("DROP TABLE alerts")
    assert nr.collect(st) == []


# ---------- grouping / counting ----------

def test_group_follows_digest_priority_then_severity(tmp_path):
    st = _db(tmp_path)
    _insert(st, catalyst="c11", subject="[C11-MED] n1 - x", severity="MED")
    _insert(st, catalyst="c11", subject="[C11-HIGH] n2 - x", severity="HIGH")
    _insert(st, catalyst="c7", subject="[C7-MED] fuse - x", severity="MED")
    grouped = nr.group(nr.collect(st))
    assert [c for c, _ in grouped] == ["c7", "c11"]          # c7 outranks c11
    assert [i.severity for i in grouped[1][1]] == ["HIGH", "MED"]


def test_group_puts_unknown_catalysts_last(tmp_path):
    st = _db(tmp_path)
    _insert(st, catalyst="zz_new", subject="[ZZ-MED] a - x")
    _insert(st, catalyst="c9", subject="[C9-MED] b - x")
    assert [c for c, _ in nr.group(nr.collect(st))] == ["c9", "zz_new"]


def test_counts_tallies_by_severity(tmp_path):
    st = _db(tmp_path)
    _insert(st, severity="HIGH", subject="[C6-HIGH] a - x")
    _insert(st, severity="MED", subject="[C6-MED] b - x")
    _insert(st, severity="MED", subject="[C6-MED] c - x")
    assert nr.counts(nr.collect(st)) == {"CRITICAL": 0, "HIGH": 1, "MED": 2, "LOG": 0}


# ---------- rendering ----------

def test_render_text_includes_explanation_and_flags(tmp_path):
    st = _db(tmp_path)
    _insert(st, subject="[C6-MED] Headline - src", emailed=1)
    _insert(st, subject="[C6-MED] Headline - src", emailed=0)
    grouped = nr.group(nr.collect(st))
    out = nr.render_text(grouped, nr.counts(nr.collect(st)), "2026-08-04", 24)
    assert "Headline" in out
    assert "价格上涨" in out                    # explanation carried through
    assert "×2 feeds" in out and "sent instantly" in out
    assert "https://example.test/article" in out


def test_render_text_empty_window():
    out = nr.render_text([], nr.counts([]), "2026-08-04", 24)
    assert "(no alerts in the window)" in out


def test_render_html_escapes_rss_supplied_text(tmp_path):
    st = _db(tmp_path)
    _insert(st, subject="[C6-MED] <script>alert(1)</script> - src")
    grouped = nr.group(nr.collect(st))
    out = nr.render_html(grouped, nr.counts(nr.collect(st)), "2026-08-04", 24)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_render_html_empty_window_is_valid():
    out = nr.render_html([], nr.counts([]), "2026-08-04", 24)
    assert "No alerts in the window." in out and out.endswith("</div>")


def test_headline_summarises_top_catalysts():
    class _I:
        pass
    grouped = [("c11", [_I()] * 3), ("c6", [_I()] * 2)]
    assert nr._headline(grouped, 5) == "5 items · C11×3, C6×2"

import importlib.util
import sys
from pathlib import Path

# daily_report.py lives in scripts/, load it as a module. Register in
# sys.modules before exec so @dataclass can resolve cls.__module__.
_spec = importlib.util.spec_from_file_location(
    "daily_report", Path(__file__).resolve().parent.parent / "scripts" / "daily_report.py")
dr = importlib.util.module_from_spec(_spec)
sys.modules["daily_report"] = dr
_spec.loader.exec_module(dr)


def _row(id, status, lines):
    return dr.Row(id=id, name=id, tier="FUSES", status=status, lines=lines)


def _full(statuses):
    """Build all 9 rows with given statuses (id->status); default quiet."""
    ids = ["C7", "C2", "C4", "C1", "C8", "C6", "C3", "C5", "C9"]
    return [dr.Row(id=i, name=i, tier="FUSES", status=statuses.get(i, dr.QUIET),
                   lines=[f"{i} detail"]) for i in ids]


def test_norm_subject_strips_prefix_and_source():
    assert dr._norm_subject("[C3-MED] OpenAI files IPO - Reuters") == "OpenAI files IPO"
    assert dr._norm_subject("plain subject") == "plain subject"


def test_parse_focus_valid():
    raw = 'noise {"title":"t","en":"this is a sufficiently long english sentence","zh":"中文"} trailing'
    got = dr._parse_focus(raw)
    assert got["title"] == "t" and got["zh"] == "中文"


def test_parse_focus_rejects_short_or_missing():
    assert dr._parse_focus('{"title":"t","en":"short"}') is None
    assert dr._parse_focus("no json here") is None


def test_analytical_focus_picks_highest_priority_firing():
    rows = _full({"C4": dr.FIRING, "C8": dr.FIRING})
    f = dr._analytical_focus(rows)
    # C4 outranks C8 in priority order → it leads.
    assert f["title"].startswith("C4")
    assert "C8" in f["en"]              # also-firing mentioned
    assert "Oracle" in f["en"]          # baked-in analysis present


def test_analytical_focus_watch_when_no_fire():
    rows = _full({"C6": dr.WATCH})
    f = dr._analytical_focus(rows)
    assert "No fuse" in f["en"]


def test_analytical_focus_all_quiet():
    rows = _full({})
    f = dr._analytical_focus(rows)
    assert "quiet" in f["en"].lower()


def test_render_html_contains_focus_and_badges():
    rows = _full({"C4": dr.FIRING})
    counts = {dr.FIRING: 1, dr.WATCH: 0, dr.QUIET: 8}
    focus = dr._analytical_focus(rows)
    html = dr.render_html(rows, counts, [], focus, "2026-06-14")
    assert "FOCUS" in html and "Oracle" in html
    assert "catalyst-tracker" in html and "Open dashboard" in html

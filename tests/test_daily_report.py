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


def test_parse_focus_tolerates_unescaped_quote_in_zh():
    # Sonnet occasionally emits a literal `"` as a Chinese quotation mark
    # inside the zh value, which breaks strict json.loads.
    raw = ('```json\n{"title": "t", "en": "this is a sufficiently long english sentence", '
           '"zh": "这是"资本开支"场景"}\n```')
    got = dr._parse_focus(raw)
    assert got is not None
    assert got["title"] == "t"
    assert got["zh"] == '这是"资本开支"场景'


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


def test_focus_history_roundtrip(tmp_path):
    from lib.state import State
    state = State("daily_report", db_path=tmp_path / "t.sqlite")
    assert dr._recent_focus_titles(state) == []
    dr._record_focus(state, "2026-07-12", "ORCL burns $30B FCF")
    dr._record_focus(state, "2026-07-13", "C10 real yield crosses 2.4%")
    got = dr._recent_focus_titles(state)
    # newest first, rendered as "date: title"
    assert got[0] == "2026-07-13: C10 real yield crosses 2.4%"
    assert got[1] == "2026-07-12: ORCL burns $30B FCF"


def test_generate_focus_injects_history_into_prompt(monkeypatch):
    captured = {}

    def fake_freeform(prompt, *, timeout=None):
        captured["prompt"] = prompt
        return '{"title":"t","en":"this is a sufficiently long english sentence","zh":"中文"}'

    monkeypatch.setattr(dr.llm, "freeform", fake_freeform)
    monkeypatch.setattr(dr.knowledge, "facts_for_prompt", lambda **kw: "")
    rows = _full({"C4": dr.FIRING})
    focus = dr.generate_focus(rows, [], history=["2026-07-12: ORCL burns $30B FCF"])
    assert focus["title"] == "t"
    assert "2026-07-12: ORCL burns $30B FCF" in captured["prompt"]
    assert "Do NOT retell" in captured["prompt"]

    # no history → placeholder, not a stray __HISTORY__ token
    dr.generate_focus(rows, [], history=None)
    assert "__HISTORY__" not in captured["prompt"]
    assert "(none)" in captured["prompt"]


def test_render_html_contains_focus_and_badges():
    rows = _full({"C4": dr.FIRING})
    counts = {dr.FIRING: 1, dr.WATCH: 0, dr.QUIET: 8}
    focus = dr._analytical_focus(rows)
    html = dr.render_html(rows, counts, [], focus, "2026-06-14")
    assert "FOCUS" in html and "Oracle" in html
    assert "catalyst-tracker" in html and "Open dashboard" in html

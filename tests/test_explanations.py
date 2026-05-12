from lib.explanations import explain, append_context, _REGISTRY


def test_every_registered_signal_has_nontrivial_text():
    for catalyst, signals in _REGISTRY.items():
        for kind, expl in signals.items():
            assert len(expl.what) > 20, (catalyst, kind)
            assert len(expl.why) > 50, (catalyst, kind)


def test_explain_returns_fallback_for_unknown_signal():
    e = explain("C9", "WHATEVER")
    assert "no detailed explanation" in e.what.lower()


def test_explain_returns_registered_signal():
    e = explain("C1", "USEFUL_LIFE_SHORTENED_6_TO_5")
    assert "useful life" in e.what.lower()
    assert "tailwind" in e.why.lower() or "depreciation" in e.why.lower()


def test_append_context_includes_both_sections():
    body = "original body line\n"
    out = append_context(body, "C4", "FCF_NEGATIVE")
    assert "original body line" in out
    assert "What this means:" in out
    assert "Why it matters:" in out
    assert "free cash flow" in out.lower()


def test_append_context_case_insensitive_catalyst():
    a = append_context("x", "c1", "USEFUL_LIFE_STUDY")
    b = append_context("x", "C1", "USEFUL_LIFE_STUDY")
    assert a == b


def test_c2_item_keys_match_distress_items_format():
    """The signal kind for C2 8-K items must match what c2_neoclouds.py emits."""
    for item in ("2.04", "4.02", "1.03"):
        e = explain("C2", f"C2_ITEM_{item}")
        assert "no detailed explanation" not in e.what.lower()

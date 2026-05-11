from pathlib import Path
from catalysts.c1_depreciation import scan_text, PATTERNS, MAX_SEVERITY_RANK

FIX = Path(__file__).parent / "fixtures"


def test_pattern_set_has_expected_keys():
    keys = {k for k, _, _ in PATTERNS}
    assert keys == {
        "USEFUL_LIFE_SHORTENED_6_TO_5",
        "USEFUL_LIFE_EXTENDED_4_TO_6",
        "USEFUL_LIFE_STUDY",
        "AMZN_SUBSET_PHRASE",
        "ESTIMATE_CHANGE",
        "META_5_5_YEARS",
        "ACCEL_DEPREC",
        "IMPAIRMENT_PPE",
    }


def test_amzn_excerpt_matches_expected_patterns():
    text = (FIX / "amzn_2024_10k_excerpt.txt").read_text()
    hits = scan_text(text)
    keys = {h["key"] for h in hits}
    assert "USEFUL_LIFE_SHORTENED_6_TO_5" in keys
    assert "AMZN_SUBSET_PHRASE" in keys
    assert "USEFUL_LIFE_STUDY" in keys
    assert "ACCEL_DEPREC" in keys


def test_meta_excerpt_matches_expected_patterns():
    text = (FIX / "meta_2024_10k_excerpt.txt").read_text()
    hits = scan_text(text)
    keys = {h["key"] for h in hits}
    assert "META_5_5_YEARS" in keys
    assert "ESTIMATE_CHANGE" in keys


def test_decoy_does_not_match():
    text = (FIX / "decoy_useful_life.txt").read_text()
    assert scan_text(text) == []


def test_severity_rank_orders_highest():
    assert MAX_SEVERITY_RANK(["MED", "HIGH", "MED"]) == "HIGH"
    assert MAX_SEVERITY_RANK(["CRITICAL", "HIGH"]) == "CRITICAL"
    assert MAX_SEVERITY_RANK(["MED"]) == "MED"


def test_snippet_is_truncated():
    text = "x " * 1000 + "from six years to five years " + "y " * 1000
    hits = scan_text(text)
    assert any(len(h["snippet"]) <= 240 for h in hits)

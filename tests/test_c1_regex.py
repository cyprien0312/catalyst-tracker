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


# --- boilerplate canaries --------------------------------------------------
# Verbatim excerpts from real filings. Each pins a false positive that reached
# production, or a real signal that must survive the fix that killed one.

def test_use_of_estimates_boilerplate_does_not_fire_impairment():
    """GAAP "Use of Estimates" boilerplate is in every 10-Q/10-K.

    It fired a spurious C1-HIGH on AMZN's Q2 2026 10-Q (accession
    0001018724-26-000026) on 2026-07-31. The excerpt keeps the genuine
    useful-life disclosure that sits ~150 chars later in the same paragraph,
    because that adjacency is what rules out any character-window guard.
    """
    text = (FIX / "amzn_use_of_estimates_note.txt").read_text()
    keys = {h["key"] for h in scan_text(text)}
    assert "IMPAIRMENT_PPE" not in keys
    # ...while the real disclosure in the very same paragraph still fires.
    assert "USEFUL_LIFE_SHORTENED_6_TO_5" in keys
    assert "AMZN_SUBSET_PHRASE" in keys


def test_asc360_impairment_policy_note_does_not_fire():
    """GOOGL's "Impairment of Long-Lived Assets" policy note describes a method,
    not a charge. Same class of bug, different boilerplate."""
    text = (FIX / "googl_impairment_policy.txt").read_text()
    assert "IMPAIRMENT_PPE" not in {h["key"] for h in scan_text(text)}


def test_real_impairment_disclosure_still_fires():
    """META's actual impairment numbers must survive the boilerplate fix.

    The excerpt deliberately opens with a trailing "... - Use of Estimates."
    cross-reference from the preceding sentence — proof the gate is scoped to
    the matched sentence and not to a surrounding window.
    """
    text = (FIX / "meta_impairment_real.txt").read_text()
    hits = {h["key"]: h for h in scan_text(text)}
    assert "IMPAIRMENT_PPE" in hits
    assert "$ 237 million" in hits["IMPAIRMENT_PPE"]["sentence"]


def test_contract_duration_does_not_fire_5_5_years():
    """"5.5 years" also describes AMZN's revenue backlog duration (Q1 2026
    10-Q) — nothing to do with depreciation."""
    text = (FIX / "amzn_contract_duration_5_5_years.txt").read_text()
    assert "META_5_5_YEARS" not in {h["key"] for h in scan_text(text)}


def test_hits_carry_the_sentence_they_came_from():
    text = (FIX / "amzn_2024_10k_excerpt.txt").read_text()
    hits = scan_text(text)
    assert hits and all(h.get("sentence") for h in hits)

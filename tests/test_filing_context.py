"""Unit tests for the sentence-level boilerplate/risk-factor gate."""
from lib.filing_context import (
    AFFIRMATIVE,
    BOILERPLATE,
    HYPOTHETICAL,
    MAX_SENTENCE_SPAN,
    find_disclosure,
    is_disclosure,
    scan,
    sentence_at,
)
import re


# --- sentence_at -----------------------------------------------------------

def test_sentence_at_returns_only_the_containing_sentence():
    text = "First sentence here. The impairment charge was taken. Third sentence."
    i = text.index("impairment")
    assert sentence_at(text, i, i + len("impairment")) == "The impairment charge was taken."


def test_sentence_at_does_not_split_on_decimals():
    text = "The deficit was $ 119.3 million as of year end."
    i = text.index("119.3")
    assert sentence_at(text, i, i + 5) == text


def test_sentence_at_does_not_split_on_abbreviations():
    text = "See Note 5 for detail. Alphabet Inc. reported an impairment of property and equipment."
    i = text.index("impairment")
    got = sentence_at(text, i, i + 10)
    assert got.startswith("Alphabet Inc. reported")
    assert "See Note 5" not in got


def test_sentence_at_falls_back_to_a_bounded_window_without_punctuation():
    # Filing tables run for thousands of characters with no sentence boundary.
    text = "word " * 4000
    i = 10000
    got = sentence_at(text, i, i + 4)
    assert len(got) <= 2 * MAX_SENTENCE_SPAN + 4


# --- marker classification -------------------------------------------------

def test_use_of_estimates_list_is_boilerplate():
    s = ("Estimates are used for, but not limited to, collectability of receivables, "
         "impairment of property and equipment and operating leases, income taxes.")
    assert BOILERPLATE.search(s)
    assert not is_disclosure(s)


def test_asc360_policy_note_is_boilerplate():
    s = ("We review leases, property and equipment, and intangible assets, excluding "
         "goodwill, for impairment when events or changes in circumstances indicate "
         "the carrying amount may not be recoverable.")
    assert not is_disclosure(s)


def test_risk_factor_conditional_is_hypothetical():
    s = ("Any adverse developments, including impairments, debt covenant defaults or "
         "other liabilities, could have a material adverse effect on our results.")
    assert HYPOTHETICAL.search(s)
    assert not is_disclosure(s)


def test_affirmative_beats_hypothetical():
    # A real disclosure that also describes what might follow must still alert.
    s = ("We recorded an impairment charge of $ 500 million on property and equipment, "
         "which may increase in future periods.")
    assert HYPOTHETICAL.search(s)
    assert AFFIRMATIVE.search(s)
    assert is_disclosure(s)


def test_plain_statement_of_fact_passes():
    s = ("Effective January 1, 2025 we changed our estimate of the useful lives of a "
         "subset of our servers and networking equipment from six years to five years.")
    assert is_disclosure(s)


def test_gate_fails_open_on_unrecognised_prose():
    # Nothing matched => treated as a disclosure. Silently dropping real signals
    # is the expensive failure mode, so the default must be to alert.
    assert is_disclosure("The board authorised a new datacenter programme.")


# --- find_disclosure -------------------------------------------------------

def test_boilerplate_earlier_in_the_document_does_not_mask_a_real_hit():
    """re.search would stop at the boilerplate and never reach the disclosure."""
    text = (
        "Estimates are used for, but not limited to, impairment of property and "
        "equipment and operating leases, income taxes. "
        + "filler. " * 200
        + "During 2025 we recorded impairment charges on property and equipment of "
          "$ 640 million."
    )
    rx = re.compile(r"impair(?:ment|ed)[^.]{0,80}property\s+and\s+equipment", re.I | re.S)
    found = find_disclosure(text, rx)
    assert found is not None
    _, sentence = found
    assert "$ 640 million" in sentence


def test_find_disclosure_returns_none_when_every_hit_is_boilerplate():
    text = ("Estimates are used for, but not limited to, impairment of property and "
            "equipment and operating leases, income taxes.")
    rx = re.compile(r"impair(?:ment|ed)[^.]{0,80}property\s+and\s+equipment", re.I | re.S)
    assert find_disclosure(text, rx) is None


def test_requires_applies_to_the_same_sentence():
    text = "The weighted-average remaining life of our long-term contracts is 5.5 years."
    rx = re.compile(r"5\.5\s+years?", re.I)
    assert find_disclosure(text, rx) is not None            # gate alone lets it through
    assert find_disclosure(text, rx, re.compile(r"useful\s+li(?:fe|ves)|servers?", re.I)) is None


# --- scan ------------------------------------------------------------------

def test_scan_reports_one_hit_per_key_with_its_sentence():
    text = "During 2025 we recorded impairment charges of $ 100 million. And again: impairment charges."
    compiled = [("CHARGE", re.compile(r"impairment\s+charges", re.I), "HIGH")]
    hits = scan(text, compiled)
    assert len(hits) == 1
    assert hits[0]["key"] == "CHARGE"
    assert "$ 100 million" in hits[0]["sentence"]

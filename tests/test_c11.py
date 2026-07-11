from datetime import date

from catalysts.c11_spacex import (
    ETF_SWING_PCT,
    LEAD_DAYS,
    UNLOCK_SCHEDULE,
    classify,
    diff_snapshots,
    parse_holdings_csv,
    tranche_severity,
    upcoming_tranches,
)


# --- unlock calendar ---

def test_upcoming_within_lead_window():
    # Day 70 tranche is 2026-08-21; 7 days before → included.
    hits = upcoming_tranches(date(2026, 8, 14))
    assert any(t.label == "Day 70" for t in hits)


def test_upcoming_excludes_past_and_far_future():
    hits = upcoming_tranches(date(2026, 8, 22))
    labels = [t.label for t in hits]
    assert "Day 70" not in labels          # yesterday
    assert "Day 90" not in labels          # 19 days out


def test_day_of_still_included():
    hits = upcoming_tranches(date(2026, 8, 21))
    assert any(t.label == "Day 70" for t in hits)


def test_musk_tranche_is_critical():
    musk = next(t for t in UNLOCK_SCHEDULE if "Musk" in t.label)
    assert tranche_severity(musk) == "CRITICAL"


def test_q3_earnings_tranche_is_high():
    q3 = next(t for t in UNLOCK_SCHEDULE if t.label.startswith("Q3'26"))
    assert tranche_severity(q3) == "HIGH"


def test_small_tranche_is_med():
    d70 = next(t for t in UNLOCK_SCHEDULE if t.label == "Day 70")
    assert tranche_severity(d70) == "MED"


def test_schedule_cumulative_monotonic():
    cums = [t.cumulative_pct for t in UNLOCK_SCHEDULE]
    assert cums == sorted(cums)


# --- news classification ---

def test_classify_lockup_expiry_high():
    assert classify("SpaceX lock-up expires next week, freeing insider shares") \
        == ("HIGH", "C11_UNLOCK_NEWS")


def test_classify_musk_sells_critical():
    assert classify("Musk sells SPCX shares after lock-up waived") \
        == ("CRITICAL", "C11_INSIDER_SUPPLY")


def test_classify_secondary_offering_critical():
    assert classify("SpaceX plans secondary offering to let insiders cash out") \
        == ("CRITICAL", "C11_INSIDER_SUPPLY")


def test_classify_index_flow_med():
    assert classify("SpaceX joins Nasdaq-100, ETF buying to hit $6 billion") \
        == ("MED", "C11_INDEX_FLOW")


def test_no_subject_returns_none():
    assert classify("Tesla lock-up expires, insiders sell") is None


def test_mission_noise_rejected():
    assert classify("SpaceX launches 23 Starlink satellites from Cape Canaveral") \
        is None


def test_mission_noise_with_market_token_still_classifies():
    text = "SpaceX launches 23 Starlink satellites; SPCX lock-up expires Monday"
    assert classify(text) == ("HIGH", "C11_UNLOCK_NEWS")


def test_critical_beats_high_when_both_present():
    text = "SpaceX lock-up waived early; unlock floods market"
    assert classify(text) == ("CRITICAL", "C11_INSIDER_SUPPLY")


# --- ETF holdings CSV parsing ---

ARK_CSV = (
    "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
    '07/10/2026,ARKQ,TESLA INC,TSLA,88160R101,"567,123","$230,563,855.65",10.85%\n'
    '07/10/2026,ARKQ,SPACE EXPLORATION TECHN-CL A,SPCX,84615Q103,"836,475","$127,278,036.00",5.99%\n'
)


def test_parse_ark_csv_finds_spcx():
    snap = parse_holdings_csv(ARK_CSV)
    assert snap == {"date": "2026-07-10", "shares": 836475.0, "weight_pct": 5.99}


def test_parse_matches_on_cusip_with_ticker_suffix():
    csv_text = (
        "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
        '07/10/2026,XFND,SPACE EXPLORATION,SPCX UQ,84615Q103,"1,000","$152,000",1.00%\n'
    )
    snap = parse_holdings_csv(csv_text)
    assert snap is not None and snap["shares"] == 1000.0


def test_parse_returns_none_when_absent():
    csv_text = (
        "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
        '07/10/2026,ARKQ,TESLA INC,TSLA,88160R101,"567,123","$230,563,855.65",10.85%\n'
    )
    assert parse_holdings_csv(csv_text) is None


# --- ETF diff semantics ---

def _snap(shares, d="2026-07-10"):
    return {"date": d, "shares": shares, "weight_pct": 5.0}


def test_diff_cut_is_high():
    sev, direction = diff_snapshots(_snap(1000, "2026-07-09"), _snap(700))
    assert sev == "HIGH" and direction.startswith("cut")


def test_diff_add_is_med():
    sev, direction = diff_snapshots(_snap(1000, "2026-07-09"), _snap(1300))
    assert sev == "MED" and direction.startswith("added")


def test_diff_below_swing_threshold_is_none():
    assert diff_snapshots(_snap(1000, "2026-07-09"),
                          _snap(1000 * (1 + (ETF_SWING_PCT - 1) / 100))) is None
    assert diff_snapshots(_snap(1000, "2026-07-09"), _snap(850)) is None


def test_diff_no_prior_is_none():
    assert diff_snapshots(None, _snap(1000)) is None


def test_lead_days_sane():
    assert 1 <= LEAD_DAYS <= 30

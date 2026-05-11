from pathlib import Path
import responses

from lib.edgar import EdgarClient
from lib.xbrl import company_concept, quarterly_only, compute_ttm, XbrlPoint

FIX = Path(__file__).parent / "fixtures"


@responses.activate
def test_company_concept_parses_usd_points():
    responses.add(
        responses.GET,
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000789019/us-gaap/PaymentsToAcquirePropertyPlantAndEquipment.json",
        body=(FIX / "xbrl_msft_capex.json").read_text(),
        status=200,
    )
    pts = company_concept(EdgarClient(), "0000789019", "PaymentsToAcquirePropertyPlantAndEquipment")
    assert len(pts) == 5
    assert pts[0].end == "2024-03-31"
    assert pts[-1].fp == "Q1"


def test_quarterly_only_synthesizes_q4():
    base = [
        XbrlPoint("2024-03-31", 10.0, "Q1", 2024, "x1", "10-Q"),
        XbrlPoint("2024-06-30", 12.0, "Q2", 2024, "x2", "10-Q"),
        XbrlPoint("2024-09-30", 14.0, "Q3", 2024, "x3", "10-Q"),
        XbrlPoint("2024-12-31", 60.0, "FY", 2024, "x4", "10-K"),
    ]
    qs = quarterly_only(base)
    fps = [p.fp for p in qs]
    assert "Q4" in fps
    q4 = next(p for p in qs if p.fp == "Q4")
    assert q4.val == 60.0 - 10.0 - 12.0 - 14.0  # = 24


def test_compute_ttm_sums_four_quarters():
    qs = [
        XbrlPoint("2024-03-31", 10.0, "Q1", 2024, "x1", "10-Q"),
        XbrlPoint("2024-06-30", 12.0, "Q2", 2024, "x2", "10-Q"),
        XbrlPoint("2024-09-30", 14.0, "Q3", 2024, "x3", "10-Q"),
        XbrlPoint("2024-12-31", 24.0, "Q4", 2024, "x4", "10-K"),
        XbrlPoint("2025-03-31", 22.0, "Q1", 2025, "x5", "10-Q"),
    ]
    assert compute_ttm(qs) == 12 + 14 + 24 + 22


def test_compute_ttm_returns_none_when_too_few():
    qs = [
        XbrlPoint("2024-03-31", 10.0, "Q1", 2024, "x1", "10-Q"),
    ]
    assert compute_ttm(qs) is None

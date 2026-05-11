"""SEC XBRL company-concept helpers."""
from __future__ import annotations

from dataclasses import dataclass

from lib.edgar import EdgarClient

CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"


@dataclass(frozen=True)
class XbrlPoint:
    end: str         # period end date YYYY-MM-DD
    val: float       # value (USD)
    fp: str          # "Q1","Q2","Q3","FY"
    fy: int
    accn: str
    form: str


def company_concept(edgar: EdgarClient, cik: str, concept: str) -> list[XbrlPoint]:
    """Fetch XBRL company-concept and return USD quarterly/annual points sorted by end date."""
    url = CONCEPT_URL.format(cik=cik, concept=concept)
    resp = edgar._get(url)
    data = resp.json()
    usd = data.get("units", {}).get("USD", [])
    seen = set()
    out: list[XbrlPoint] = []
    for u in usd:
        end = u.get("end")
        fp = u.get("fp") or ""
        fy = u.get("fy") or 0
        if not end:
            continue
        key = (end, fp, fy)
        if key in seen:
            continue
        seen.add(key)
        out.append(XbrlPoint(
            end=end,
            val=float(u.get("val", 0)),
            fp=fp,
            fy=int(fy) if fy else 0,
            accn=u.get("accn") or "",
            form=u.get("form") or "",
        ))
    out.sort(key=lambda p: p.end)
    return out


def quarterly_only(points: list[XbrlPoint]) -> list[XbrlPoint]:
    """Filter to single-quarter datapoints (fp in Q1..Q3 or implied Q4 = FY - Q1+Q2+Q3).

    The XBRL feed mixes YTD totals with quarterly observations. Quarterlies are
    the items whose fp is Q1/Q2/Q3 or where form is 10-Q. Q4 we synthesize as
    FY10K minus the three preceding 10-Qs in the same fy.
    """
    quarter_like = [p for p in points if p.fp in ("Q1", "Q2", "Q3") and p.form == "10-Q"]
    annuals = [p for p in points if p.fp == "FY" and p.form == "10-K"]
    out: list[XbrlPoint] = list(quarter_like)
    # Synthesize Q4 = FY - (Q1+Q2+Q3 in same fy)
    by_fy = {p.fy: p for p in annuals}
    for fy, ann in by_fy.items():
        prior_qs = [p for p in quarter_like if p.fy == fy]
        if len(prior_qs) == 3:
            q4_val = ann.val - sum(p.val for p in prior_qs)
            out.append(XbrlPoint(
                end=ann.end, val=q4_val, fp="Q4", fy=fy, accn=ann.accn, form="10-K",
            ))
    out.sort(key=lambda p: p.end)
    return out


def compute_ttm(quarterly: list[XbrlPoint], anchor_end: str | None = None) -> float | None:
    """Sum of 4 most recent quarterly points ending ≤ anchor_end (or latest)."""
    pts = quarterly
    if anchor_end is not None:
        pts = [p for p in pts if p.end <= anchor_end]
    if len(pts) < 4:
        return None
    return sum(p.val for p in pts[-4:])

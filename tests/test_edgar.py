from pathlib import Path
import responses
from lib.edgar import EdgarClient, Filing

FIX = Path(__file__).parent / "fixtures"


@responses.activate
def test_recent_filings_parses_submissions_json():
    body = (FIX / "edgar_submissions_amzn.json").read_text()
    responses.add(
        responses.GET,
        "https://data.sec.gov/submissions/CIK0001018724.json",
        body=body, status=200, content_type="application/json",
    )
    c = EdgarClient()
    filings = c.recent_filings("0001018724", forms=("10-K", "8-K"), limit=10)
    assert len(filings) == 2
    f0 = filings[0]
    assert isinstance(f0, Filing)
    assert f0.accession == "0001018724-25-000004"
    assert f0.form == "10-K"
    assert f0.filed_date == "2025-02-07"
    assert f0.primary_document == "amzn-20241231.htm"
    assert f0.cik == "0001018724"
    assert f0.url.endswith("/000101872425000004/amzn-20241231.htm")


@responses.activate
def test_recent_filings_filters_by_form():
    body = (FIX / "edgar_submissions_amzn.json").read_text()
    responses.add(
        responses.GET,
        "https://data.sec.gov/submissions/CIK0001018724.json",
        body=body, status=200,
    )
    c = EdgarClient()
    only_10k = c.recent_filings("0001018724", forms=("10-K",))
    assert [f.form for f in only_10k] == ["10-K"]


@responses.activate
def test_get_filing_text_strips_html():
    f = Filing(
        cik="0001018724",
        accession="0001018724-25-000004",
        form="10-K",
        filed_date="2025-02-07",
        primary_document="amzn-20241231.htm",
        url="https://www.sec.gov/Archives/edgar/data/1018724/000101872425000004/amzn-20241231.htm",
    )
    responses.add(
        responses.GET, f.url,
        body="<html><body><p>Hello <b>world</b></p><script>x()</script></body></html>",
        status=200,
    )
    c = EdgarClient()
    text = c.get_filing_text(f)
    assert "Hello world" in text
    assert "x()" not in text


@responses.activate
def test_filings_expose_8k_items():
    body = (FIX / "edgar_submissions_apld.json").read_text()
    responses.add(
        responses.GET,
        "https://data.sec.gov/submissions/CIK0001144879.json",
        body=body, status=200,
    )
    c = EdgarClient()
    filings = c.recent_filings("0001144879", forms=("10-Q", "8-K"))
    by_form = {f.form: f for f in filings}
    assert by_form["10-Q"].items == ()
    assert by_form["8-K"].items == ("2.04", "7.01")


@responses.activate
def test_user_agent_header_is_sent(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "catalyst-tracker test@example.com")
    body = (FIX / "edgar_submissions_amzn.json").read_text()
    responses.add(
        responses.GET,
        "https://data.sec.gov/submissions/CIK0001018724.json",
        body=body, status=200,
    )
    c = EdgarClient()
    c.recent_filings("0001018724")
    sent = responses.calls[0].request
    assert sent.headers["User-Agent"] == "catalyst-tracker test@example.com"

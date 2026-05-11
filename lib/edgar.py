import re
from dataclasses import dataclass
from typing import Iterable

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from lib.config import sec_user_agent
from lib.rate_limit import TokenBucket

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary}"

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.I | re.S)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.I | re.S)
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Filing:
    cik: str
    accession: str
    form: str
    filed_date: str
    primary_document: str
    url: str


def _strip_html(html: str) -> str:
    s = _SCRIPT_RE.sub(" ", html)
    s = _STYLE_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


class EdgarClient:
    def __init__(self, min_interval: float = 0.2):
        self._bucket = TokenBucket(min_interval)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = sec_user_agent()
        self._session.headers["Accept-Encoding"] = "gzip, deflate"

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=8),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def _get(self, url: str) -> requests.Response:
        self._bucket.wait()
        r = self._session.get(url, timeout=30)
        r.raise_for_status()
        return r

    def recent_filings(
        self,
        cik: str,
        forms: Iterable[str] = ("10-K", "10-Q", "8-K"),
        limit: int = 20,
    ) -> list[Filing]:
        url = SUBMISSIONS_URL.format(cik=cik)
        data = self._get(url).json()
        rec = data["filings"]["recent"]
        accs = rec["accessionNumber"]
        out: list[Filing] = []
        wanted = set(forms)
        for i, acc in enumerate(accs):
            form = rec["form"][i]
            if form not in wanted:
                continue
            primary = rec["primaryDocument"][i]
            cik_int = str(int(cik))
            acc_nodash = acc.replace("-", "")
            out.append(
                Filing(
                    cik=cik,
                    accession=acc,
                    form=form,
                    filed_date=rec["filingDate"][i],
                    primary_document=primary,
                    url=ARCHIVE_URL.format(
                        cik_int=cik_int, acc_nodash=acc_nodash, primary=primary
                    ),
                )
            )
            if len(out) >= limit:
                break
        return out

    def get_filing_text(self, filing: Filing) -> str:
        return _strip_html(self._get(filing.url).text)

# AI Infrastructure Bubble-Stress Catalyst Tracker — Claude Code Implementation Plan

## TL;DR
- **Build it on GitHub Actions (public repo)**, with SQLite persisted via `actions/cache` + git-committed snapshots, Gmail SMTP for alerts, and a static HTML dashboard published to GitHub Pages. This is the only stack that gives you free scheduling, free secrets, free egress, free persistence, free hosting, and free observability in one place — with no credit card.
- **All 5 catalysts are achievable with free, public primary sources**: SEC EDGAR (`data.sec.gov` + `efts.sec.gov`), FINRA's free 4-hour-delayed Fixed Income public site, PJM/ERCOT/CAISO queue XLSX downloads, Yahoo Finance via `yfinance`, FRED via free API key, EIA's free open-data API, and RSS feeds from WSJ, Reuters, Bloomberg, Seeking Alpha, and SEC EDGAR's own filing feeds.
- **Trigger logic is concrete and regex-pinned to the actual filing language Amazon, Meta, and Microsoft used in 2024–2025** (e.g., `"from six years to five years"`, `"5\.5 years"`, `"useful life study"`) — this minimizes false positives from generic AI commentary while catching real estimate changes the moment a 10-K/10-Q hits EDGAR.

---

## Key Findings (Decisions Already Made)

1. **Pick GitHub Actions + GitHub Pages** as the substrate. Public repos get unlimited Linux minutes, native cron, free secrets, and a free static dashboard host. Every other free tier has either a credit-card requirement, 12-month tier expiry, or workflow that doesn't fit "schedule, scrape, persist, email."
2. **Primary sources beat aggregators.** SEC EDGAR JSON APIs, FINRA's public bond pages, PJM/ERCOT/CAISO official XLSX exports, EIA, and FRED are all free and rate-limited but unrestricted. Avoid `sec-api.io` (paid), Finnhub (paid above tiny tier), and any "TRACE API."
3. **Pin regex to verbatim 10-K/10-Q language** that hyperscalers and neoclouds already used in 2024–2025 (Amazon, Meta, MSFT, Applied Digital). This converts vague "watch for X" into deterministic CI-tested detectors.
4. **SQLite committed to the repo** is the right persistence layer: durable history, free, queryable, and easy to inspect on GitHub's web UI.
5. **Gmail SMTP with App Password** is the right alert channel. Truly free, no card, more than enough volume.

---

## Details

## 1. Recommended Cloud Platform: **GitHub Actions (public repo) + GitHub Pages**

### Comparison

| Platform | Free quota | Scheduling | Secrets | Persistence | Email | Verdict |
|---|---|---|---|---|---|---|
| **GitHub Actions (public repo)** | **Unlimited minutes** for public repos; 2,000 min/mo private | `cron:` native (5-min minimum, often 10–30 min late) | First-class `secrets.*` | `actions/cache` + git commit + artifacts | SMTP works | ✅ **Pick this** |
| AWS Lambda + EventBridge | 1M req/mo, 400k GB-s; EventBridge free | Excellent | Secrets Manager $0.40/secret/mo (not free) or env vars | Need DynamoDB / S3 (free tier expires after 12 mo) | SES requires verified domain; 200/day free | Strong but card required and 12-month expiry |
| Google Cloud Run + Scheduler | 2M req/mo, Cloud Scheduler 3 free jobs | Good | Secret Manager free up to 6 versions | Firestore free | SMTP via SendGrid | Card required, more setup |
| Oracle Cloud Always Free | 2 AMD VMs + 4 ARM VMs forever | cron on VM | Plain env / Vault | Disk on VM | SMTP | Most powerful but reclamation risk; account creation hostile |
| Fly.io free | Removed Sept 2024; minimal free now | n/a | n/a | n/a | n/a | ❌ No longer free |

### Why GitHub Actions wins for this workload
1. **Public repo = unlimited Linux minutes**, and a catalyst tracker is read-only intelligence — no secrets need to be in the repo (only in `secrets.*`). Make the repo public so you also get the free dashboard via GitHub Pages and unlimited cache.
2. **Native cron** with `workflow_dispatch` for manual runs and `repository_dispatch` for webhook-style triggers (e.g., from cron-job.org if you need stricter timing).
3. **Secrets management is built-in** (`${{ secrets.GMAIL_APP_PASSWORD }}`) with no extra cost, no setup, no rotation pain.
4. **State persistence has 3 free options** layered for resilience:
   - `actions/cache@v4` (10 GB/repo, 7-day eviction) for hot state.
   - `actions/upload-artifact@v4` (90-day retention) for medium-term snapshots.
   - **Git commit of `state/*.sqlite`** back to the repo via `stefanzweifel/git-auto-commit-action` for permanent history (per Simon Willison's "git scraping" pattern).
5. **GitHub Pages** publishes a free static dashboard from the same repo's `docs/` folder — zero extra infra.
6. **Debugging is trivial**: every run produces logs viewable in the browser, with re-run-failed-jobs, artifact downloads, and `tmate` SSH-into-runner support.

### Cost ceiling check
At our designed cadence (see §4), the heaviest day uses **~22 minutes of runner time**. Even on a private repo, that's **~660 min/mo — well within the 2,000-min free tier**. On a public repo, it's free regardless. We will recommend public.

### Known sharp edge
GitHub Actions cron is best-effort and **silently disables scheduled workflows after 60 days of repo inactivity**. We mitigate with (a) a daily commit of the SQLite state file (which qualifies as activity) and (b) a `keepalive` workflow that pushes a no-op timestamp to `state/heartbeat.txt` weekly.

---

## 2. Repo Structure

```
catalyst-tracker/
├── .github/
│   └── workflows/
│       ├── catalyst1_depreciation.yml      # Daily + earnings-window burst
│       ├── catalyst2_neoclouds.yml         # Hourly during US market hours
│       ├── catalyst3_openai.yml            # Every 30 min
│       ├── catalyst4_capex.yml             # Daily + earnings-week burst
│       ├── catalyst5_grid.yml              # Daily 06:00 UTC
│       ├── dashboard_build.yml             # After every catalyst run
│       └── keepalive.yml                   # Weekly heartbeat
├── catalysts/
│   ├── __init__.py
│   ├── base.py                             # CatalystBase ABC, alert dispatch, dedup
│   ├── c1_depreciation.py
│   ├── c2_neoclouds.py
│   ├── c3_openai.py
│   ├── c4_capex.py
│   └── c5_grid.py
├── lib/
│   ├── __init__.py
│   ├── edgar.py                            # SEC EDGAR client w/ rate limit, UA
│   ├── trace.py                            # FINRA Fixed Income scraper
│   ├── prices.py                           # yfinance wrapper, short interest
│   ├── rss.py                              # feedparser wrapper, dedup by GUID
│   ├── grid_queues.py                      # PJM/ERCOT/CAISO downloaders
│   ├── eia.py                              # EIA open data API client
│   ├── fred.py                             # FRED client
│   ├── transcripts.py                      # Motley Fool / SA scraper
│   ├── notify.py                           # Gmail SMTP + dedup
│   ├── state.py                            # SQLite wrapper
│   └── config.py                           # Tickers, CIKs, regex patterns
├── state/
│   ├── tracker.sqlite                      # Committed back after each run
│   └── heartbeat.txt
├── docs/                                   # GitHub Pages source
│   ├── index.html                          # Auto-generated dashboard
│   └── data/status.json
├── tests/
│   ├── test_edgar.py
│   ├── test_regex.py                       # Unit tests on real filing snippets
│   └── fixtures/
│       └── amzn_2024_10k_excerpt.txt
├── scripts/
│   ├── build_dashboard.py
│   ├── backfill.py                         # One-time historical seeding
│   └── test_alert.py                       # Send test email
├── requirements.txt
├── README.md
└── .gitignore
```

**Naming conventions**
- Catalyst modules: `c{N}_{slug}.py`, each exposing `class Catalyst{N}(CatalystBase)` with `def run() -> list[Alert]`.
- State tables: `c{N}_{table}` (e.g., `c1_useful_life_history`).
- Secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_TO`, `EIA_API_KEY`, `FRED_API_KEY`, `SEC_USER_AGENT`.

---

## 3. Per-Catalyst Implementation

### Common dependencies (`requirements.txt`)
```
requests>=2.32
beautifulsoup4>=4.12
lxml>=5.2
feedparser>=6.0
pandas>=2.2
openpyxl>=3.1            # XLSX read for grid queues
yfinance>=0.2.40
sec-edgar-downloader>=5.0  # optional convenience
python-dateutil>=2.9
tenacity>=8.4            # retry/backoff
jinja2>=3.1              # dashboard
```

No paid packages. No API keys are required for SEC, FINRA, PJM, ERCOT, CAISO, RSS, yfinance, or Motley Fool. Free keys (no card) for **EIA** (https://www.eia.gov/opendata/register.php) and **FRED** (https://fred.stlouisfed.org/docs/api/api_key.html).

---

### CATALYST 1 — GPU Depreciation Useful-Life Changes
**Module:** `catalysts/c1_depreciation.py`
**Cadence:** Daily 11:00 UTC; every 2 hrs during the 14-day window after each watchlist company's quarter-end (auto-detected from EDGAR submissions JSON).

**Watchlist (verified CIKs, with leading zeros):**
| Ticker | Company | CIK |
|---|---|---|
| MSFT | Microsoft | 0000789019 |
| GOOGL | Alphabet | 0001652044 |
| META | Meta Platforms | 0001326801 |
| AMZN | Amazon | 0001018724 |
| ORCL | Oracle | 0001341439 |
| NVDA | NVIDIA | 0001045810 |

**Data sources:**
- Per-company submissions feed: `https://data.sec.gov/submissions/CIK{cik10}.json` — lists all filings; we scan for new `10-K` / `10-Q` accessions since last run.
- Filing document: `https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}/{primaryDocument}`.
- Backstop full-text search: `https://efts.sec.gov/LATEST/search-index?q=%22useful+life%22&forms=10-K,10-Q&dateRange=custom&startdt=...&enddt=...` (POST also works; GET works for simple queries).
- Required header: `User-Agent: catalyst-tracker your.email@example.com` (SEC enforces this; rate limit ≤10 req/sec; we rate-limit at 5 req/sec with 150 ms spacing).

**Trigger conditions (fire alert if ANY match in the just-filed 10-K/10-Q text):**

| Pattern (case-insensitive regex) | Severity | Source for pattern |
|---|---|---|
| `from\s+(?:six\|6)\s+years?\s+to\s+(?:five\|5)\s+years?` | HIGH | Amazon FY2024 10-K verbatim |
| `from\s+(?:four\|4)\s+years?\s+to\s+(?:six\|6)\s+years?` | MED (historical baseline; alert only if NEW filer) | MSFT FY2024 10-K verbatim |
| `useful\s+life\s+stud(?:y\|ies)` | HIGH | Amazon trigger phrase |
| `subset\s+of\s+(?:our\s+)?servers?\s+and\s+networking\s+equipment` | HIGH | Amazon verbatim |
| `(?:increase\|extend\|extension\|reduce\|shorten).{0,40}useful\s+liv(?:es\|e)` | HIGH | generic |
| `change\s+in\s+(?:accounting\s+)?estimate.{0,80}(?:server\|network\|equipment)` | HIGH | Meta FY2024 10-K verbatim |
| `(?:5\.5\|five\s+and\s+a\s+half)\s+years?` | MED | Meta verbatim |
| `accelerated\s+depreciation` AND `(?:server\|GPU\|network)` | HIGH | impairment proxy |
| `impair(?:ment\|ed)` AND `property\s+and\s+equipment` | HIGH | impairment line |

> ⚠️ **A pattern hit alone is no longer sufficient to alert (changed 2026-08-05).**
> Every hit is gated by `lib/filing_context.py`, which rejects the match if the
> *sentence* it lands in is accounting-policy boilerplate or forward-looking risk
> language. `impair… property and equipment` in particular matches the "Use of
> Estimates" note of every single 10-Q ever filed. See §3.1.

**Verbatim anchor text for unit tests** — from Amazon's 10-K (accession `0001018724-25-000004`, filed 2025-02-07, period 2024-12-31, file `amzn-20241231.htm`):

> "We completed our most recent servers and networking equipment useful life study in Q4 2024, and are changing the useful lives of a subset of our servers and networking equipment, effective January 1, 2025, from six years to five years. … we anticipate a decrease in 2025 operating income of approximately $0.7 billion."

> "We recorded approximately $920 million of accelerated depreciation and related charges for the quarter ended December 31, 2024 …"

> "These two changes above are due to an increased pace of technology development, particularly in the area of artificial intelligence and machine learning."

From Meta's FY2024 10-K (accession `0001326801-25-000017`, file `meta-20241231.htm`):

> "In January 2025, we completed an assessment of the useful lives of certain servers and network assets, which resulted in an increase in their estimated useful life to 5.5 years, effective beginning fiscal year 2025. … we expect this change in accounting estimate will reduce our full-year 2025 depreciation expense by approximately $2.9 billion."

These are the literal strings the regex must match in production. They live in `tests/fixtures/` as canary tests — CI fails if our regex stops matching them after refactors.

### §3.1 Context gate (added 2026-08-05)

The patterns above match *vocabulary*, not *disclosures*. Filings state the same
words in three voices, only one of which is a signal:

| voice | example | alert? |
|---|---|---|
| **policy boilerplate** | "Estimates are used for, but not limited to, … impairment of property and equipment …" | no |
| **risk-factor hypothetical** | "any adverse developments … including … debt covenant defaults …, could have a material adverse effect" | no |
| **disclosure** | "total impairment losses for property and equipment were $237 million" | yes |

`lib/filing_context.py` classifies the sentence a hit lands in and drops the
first two. It **fails open** — an unrecognised sentence still alerts, because a
suppressed real signal is silent and therefore the more expensive error.

Scope is the sentence and **not** a character window. In AMZN's FY2025 10-K the
genuine useful-life change sits ~150 chars after the "but not limited to" list,
so any window wide enough to catch the boilerplate also swallows the real
signal. `tests/fixtures/amzn_use_of_estimates_note.txt` pins exactly that
adjacency.

Because boilerplate reliably precedes real disclosures in a filing, the scan
walks **every** occurrence (`finditer`) rather than the first (`re.search`) —
otherwise the policy note near the top masks the disclosure in the notes below.

**Core code:**
```python
# catalysts/c1_depreciation.py
import re, time
from lib.edgar import EdgarClient
from lib.state import State
from lib.notify import send_alert
from catalysts.base import CatalystBase, Alert

WATCHLIST = {  # ticker: cik10
    "MSFT": "0000789019", "GOOGL": "0001652044", "META": "0001326801",
    "AMZN": "0001018724", "ORCL": "0001341439", "NVDA": "0001045810",
}

PATTERNS = [
    ("USEFUL_LIFE_SHORTENED_6_TO_5", r"from\s+(?:six|6)\s+years?\s+to\s+(?:five|5)\s+years?", "HIGH"),
    ("USEFUL_LIFE_EXTENDED_4_TO_6", r"from\s+(?:four|4)\s+years?\s+to\s+(?:six|6)\s+years?", "MED"),
    ("USEFUL_LIFE_STUDY", r"useful\s+life\s+stud(?:y|ies)", "HIGH"),
    ("AMZN_SUBSET_PHRASE", r"subset\s+of\s+(?:our\s+)?servers?\s+and\s+networking\s+equipment", "HIGH"),
    ("ESTIMATE_CHANGE", r"change\s+in\s+(?:accounting\s+)?estimate[^.]{0,120}(?:server|network|equipment)", "HIGH"),
    ("META_5_5_YEARS", r"(?:5\.5|five\s+and\s+a\s+half)\s+years?", "MED"),
    ("ACCEL_DEPREC", r"accelerated\s+depreciation[^.]{0,100}(?:server|gpu|network)", "HIGH"),
    ("IMPAIRMENT_PPE", r"impair(?:ment|ed)[^.]{0,80}property\s+and\s+equipment", "HIGH"),
]
COMPILED = [(k, re.compile(p, re.I | re.S), s) for k, p, s in PATTERNS]

class Catalyst1(CatalystBase):
    name = "GPU Depreciation Useful-Life Changes"

    def run(self) -> list[Alert]:
        edgar, st = EdgarClient(), State("c1")
        alerts = []
        for ticker, cik in WATCHLIST.items():
            for filing in edgar.recent_filings(cik, forms=("10-K","10-Q","8-K")):
                if st.seen("c1_filings", filing.accession): continue
                text = edgar.get_filing_text(filing)
                hits = [(k,s,m.group(0)[:240]) for k,rx,s in COMPILED for m in [rx.search(text)] if m]
                if hits:
                    alerts.append(Alert(
                        catalyst="C1", severity=max(h[1] for h in hits),
                        subject=f"[C1-{max(h[1] for h in hits)}] {ticker} {filing.form}: depreciation language change detected",
                        body=self._render(ticker, filing, hits),
                    ))
                st.mark_seen("c1_filings", filing.accession)
                time.sleep(0.15)  # SEC rate limit
        return alerts
```

---

### CATALYST 2 — Neocloud Distress
**Module:** `catalysts/c2_neoclouds.py`
**Cadence:** Hourly 13:30–21:00 UTC weekdays (US market hours), once on weekends.

**Watchlist (verified CIKs):**
| Ticker | Company | CIK |
|---|---|---|
| CRWV | CoreWeave | 0001769628 |
| APLD | Applied Digital | 0001144879 |
| IREN | IREN Limited (Iris Energy) | 0001878848 |
| NBIS | Nebius Group | 0001513845 |

**Data sources:**
- SEC submissions JSON for each CIK (same as C1).
- Filing text full-scan for going-concern / covenant phrases.
- FINRA bond pages: `https://www.finra.org/finra-data/fixed-income/corp-and-agency` — search by issuer name and capture last trade price; specific bonds (e.g., CoreWeave's 9.25% senior notes due 2030, CUSIP-based) can be fetched at `https://www.finra.org/finra-data/fixed-income/corporate-bond-detail/{symbol}`. Free public site requires accepting the Fixed Income User Agreement once via cookie.
- `yfinance` for stock price, volume, and intraday gap detection: `yf.Ticker("CRWV").history(period="60d", interval="1d")`.
- Short interest: scrape `https://www.nasdaq.com/market-activity/stocks/{ticker}/short-interest` (free, public), bi-monthly.

**Trigger conditions:**

| Signal | Threshold | Severity |
|---|---|---|
| 10-Q/10-K text matches `going\s+concern\|substantial\s+doubt` | first occurrence per filing | CRITICAL |
| Text matches `covenant\s+(breach\|default\|waiver\|amendment)` | new occurrence | HIGH |
| Text matches `material\s+adverse\s+(change\|effect)` near `liquidity\|debt` | new occurrence | HIGH |
| 8-K with item 2.04 (debt acceleration) or 4.02 (non-reliance) or 1.03 (bankruptcy) | filed | CRITICAL |
| 1-day stock move ≤ –15% on volume ≥ 3× 20-day avg | daily close | HIGH |
| Bond price < 90 (cents on dollar) on most recent trade | daily | HIGH |
| Short interest ≥ 20% of float | bi-monthly update | MED |
| S&P / Moody's downgrade headline | RSS hit | HIGH |

**Anchor verbatim** — Applied Digital 10-Q (accession `0001628280-25-017684`, period 2025-02-28):

> "The Company had a working capital deficit of $119.3 million as of February 28, 2025 which raised substantial doubt about the Company's ability to continue as a going concern."

This goes into `tests/fixtures/apld_10q_excerpt.txt` and our regex `r"substantial\s+doubt[^.]{0,80}going\s+concern"` must keep matching it.

For 8-K item detection, EDGAR submissions JSON includes `items` — we trigger on `2.04` (Triggering Events Accelerating Direct Financial Obligation), `4.02` (Non-Reliance), and `1.03` (Bankruptcy).

For bond prices: FINRA's fixed-income search page is HTML-rendered; the practical approach is a once-a-day BeautifulSoup scrape against the issuer detail page, parsing the most-recent trade row. Note: FINRA's real-time TRACE feed is **paid — $1,500/month per data set per FINRA's official TRACE Pricing schedule** (BTDS, ATDS, SPDS, or 144A; a subscriber requiring all four corporate/agency data sets would pay $6,000/month total). We use the **delayed (4-hour) public display**, which is **No Charge for Personal, Non-Commercial Use** per the same schedule.

---

### CATALYST 3 — OpenAI Financial Stress
**Module:** `catalysts/c3_openai.py`
**Cadence:** Every 30 min, 10:00–22:00 UTC; daily at 06:00 UTC for SoftBank/MSFT filings.

**Data sources:**
- **MSFT 10-Q full-text scan** (uses C1's edgar client) — search for `OpenAI`, `unconsolidated invest`, `equity method invest`, `loss on equity invest`. MSFT has historically disclosed an "Other income/expense" line and a separate equity-method loss line.
- **SoftBank earnings PDF** — semi-annual; auto-discover from https://group.softbank/en/ir/financials, run keyword scan for "OpenAI" and "Vision Fund."
- **News RSS feeds** (parsed via `feedparser`):
  - WSJ Tech: `https://feeds.content.dowjones.io/public/rss/RSSWSJD`
  - WSJ Business: `https://feeds.content.dowjones.io/public/rss/RSSBusinessNews`
  - Reuters Technology (via Google News fallback): `https://news.google.com/rss/search?q=OpenAI+when:1d&hl=en-US&gl=US&ceid=US:en`
  - Bloomberg Technology: `https://feeds.bloomberg.com/technology/news.rss`
  - The Information (free headlines): `https://www.theinformation.com/feed`
  - Seeking Alpha OpenAI tag: `https://seekingalpha.com/api/sa/combined/OPENAI.xml` (when available; fall back to Google News query for `site:seekingalpha.com OpenAI`)
  - CNBC Technology: `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910`
- **EDGAR full-text search** for "OpenAI" in 10-K/10-Q filings: `https://efts.sec.gov/LATEST/search-index?q=%22OpenAI%22&forms=10-K,10-Q&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD`.

**Keyword set (alert if ≥1 fresh hit):**
- `"OpenAI revenue"`, `"OpenAI burn rate"`, `"OpenAI losses"`, `"Sarah Friar"`,
- `"OpenAI bond"`, `"OpenAI prospectus"`, `"OpenAI debt"`, `"OpenAI IPO"`,
- `"OpenAI valuation cut"`, `"OpenAI down round"`, `"OpenAI restructuring"`,
- `"Microsoft OpenAI write-down"`, `"OpenAI default"`, `"OpenAI covenant"`.

**Severity logic:**
- CRITICAL: any of `bond | prospectus | default | covenant | write-down | impair | restructuring`.
- HIGH: any of `burn rate | losses | down round | valuation cut | IPO`.
- MED: bare `Sarah Friar` mentions or `revenue` mentions.

**Quantitative triggers (numeric extraction with regex):**
- `r"OpenAI[^.]{0,80}\$(\d+(?:\.\d+)?)\s*(billion|trillion)\s+(?:in\s+)?(?:revenue|burn|losses)"` — log to SQLite, alert if revenue figure decreases QoQ or burn figure increases >25% QoQ.

**Baseline references (so the system has context, stored in `c3_baselines`):**
- **2025 ARR: "$20B+"** per CFO Sarah Friar's January 19, 2026 blog post, as quoted by Sherwood News: *"Revenue followed the same curve growing 3X year over year, or 10X from 2023 to 2025: $2B ARR in 2023, $6B in 2024, and $20B+ in 2025. This is never-before-seen growth at such scale."*
- **2025 net loss: ~$9 billion** per Fortune (Nov 12, 2025), citing investor documents: *"total spending of roughly $22 billion this year against $13 billion in sales, resulting in a net loss of $9 billion."*
- **2026 projected cash burn: ~$17 billion** per Sacra citing the same investor documents: *"OpenAI projected cash burn of approximately $9B in 2025 and $17B in 2026."*

**Dedup:** RSS items keyed by `(feed_url, guid)`; news items by SHA-256 of normalized title + first 200 chars of summary, retained 30 days.

---

### CATALYST 4 — Hyperscaler Capex Guidance Cuts
**Module:** `catalysts/c4_capex.py`
**Cadence:** Daily 11:30 UTC. During earnings weeks (auto-detected from each company's expected report date), every 30 min 20:00–01:00 UTC.

**Watchlist:** MSFT, GOOGL, META, AMZN, ORCL (CIKs above).

**Data sources:**
- **10-Q XBRL Company Facts API** — quarterly capex and OCF without scraping:
  `https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/PaymentsToAcquirePropertyPlantAndEquipment.json`
  `https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/NetCashProvidedByUsedInOperatingActivities.json`
  These return all historical quarterly USD values. Compute trailing-twelve-months capex/OCF.
- **Earnings transcripts (free):**
  - Motley Fool: `https://www.fool.com/earnings-call-transcripts/` (HTML scrape; per-company filter URL pattern `https://www.fool.com/quote/nasdaq/{ticker}/`).
  - SEC EDGAR 8-K Item 2.02 attachments often contain the prepared remarks PDF.
  - Seeking Alpha transcripts now require login; use it as a fallback only.
- **Yahoo Finance** for FCF trend: `yfinance.Ticker(t).cashflow` and `.quarterly_cashflow`.

**Trigger conditions:**

| Signal | Threshold | Severity |
|---|---|---|
| TTM Capex/OCF ratio crosses ≥ 110% | computed from XBRL | HIGH |
| TTM Capex/OCF ratio QoQ jump ≥ 15 pp | computed | MED |
| YoY Capex growth rate decelerates from > 50% to < 20% | computed | HIGH |
| Transcript regex hit: `r"(more disciplined\|moderating\|tempered\|slower pace)\b.{0,60}(capex\|capital expenditure\|spend\|invest)"` | new transcript | HIGH |
| Transcript regex hit: `r"capex.{0,40}(grow\|increase) significantly"` (continuing aggressive language) | tracked, NO alert | LOG |
| Transcript regex hit: `r"(reduc\|cut\|lower\|trim).{0,30}(2026\|2027) capital"` | new transcript | CRITICAL |
| FCF turns negative (TTM) | yfinance | HIGH |

**Context for thresholds:** Per MarketWise citing Bank of America research, the five largest hyperscalers (MSFT, AMZN, GOOGL, META, ORCL) will spend "about 90% of their operating cash flow on capex in 2026, up from 65% in 2025." Per Introl's Nov 2025 analysis citing the same Bank of America note, the figure rises to **94% after accounting for dividends and buybacks**, and a UBS research note (also cited by Introl) puts it at "nearly 100% … compared to a 10-year average of 40%." Crossing **110%** is the threshold where companies are explicitly pre-funding capex with debt or balance-sheet drawdowns — historically a classic late-cycle signal.

**Alert subject line examples:**
- `[C4-HIGH] MSFT: TTM Capex/OCF crossed 112% (was 89% prior quarter)`
- `[C4-CRITICAL] META: Earnings call transcript hit "lower 2026 capital expenditures"`

---

### CATALYST 5 — Grid Bottlenecks / Power Constraints
**Module:** `catalysts/c5_grid.py`
**Cadence:** Daily 10:00 UTC. Also re-runs the first business day of each month for ERCOT GIS (released first Friday of each month).

**Data sources:**
- **PJM new-services queue** (XLSX): `https://services.pjm.com/PJMPlanningApi/api/Queues/ExportToExcel` — public, no auth; the Excel file linked from `https://services.pjm.com/PJMPlanningApi/api/Queues` returns the full active queue. (As an alternative, `interconnection.fyi` aggregates daily but scraping the source directly is preferred.)
- **ERCOT GIS report**: monthly, posted under `https://www.ercot.com/gridinfo/resource`. Programmatic landing: `https://mis.ercot.com/misapp/GetReports.do?reportTypeId=15933`.
- **CAISO public queue**: `https://www.caiso.com/documents/publicqueuereport.xlsx` (overwritten in place each cycle).
- **Yahoo Finance** for utility capex: `yfinance.Ticker(t).quarterly_cashflow.loc["Capital Expenditure"]` for VST (CIK 0001692819), CEG (0001868275), NEE (0000753308), TLN (0001622536).
- **Henry Hub natural gas long-dated futures**:
  - EIA API series `NG.RNGC1.D` (Henry Hub spot) and `NG.RNGC2.D…RNGC12.D` (futures contracts 1–12) at `https://api.eia.gov/v2/seriesid/NG.RNGC1.D?api_key={KEY}`.
  - FRED: `https://api.stlouisfed.org/fred/series/observations?series_id=DHHNGSP&api_key={KEY}&file_type=json`.
- **News alerts** via Google News RSS:
  `https://news.google.com/rss/search?q=%22data+center%22+%22power+delay%22+OR+%22grid+bottleneck%22+OR+%22interconnection+delay%22&when:1d`.

**Trigger conditions:**

| Signal | Threshold | Severity |
|---|---|---|
| PJM queue: # of new data-center–flagged projects withdrawn week-over-week ≥ 5 | weekly | HIGH |
| ERCOT GIS: total active queue MW drops MoM by ≥ 5% | monthly | MED |
| CAISO queue: large-load (>100 MW) projects suspended this cycle ≥ 3 | monthly | HIGH |
| Utility 8-K with `r"power\s+(?:delay\|deferral)"` or `data\s+center.{0,40}delay` | filed | HIGH |
| Henry Hub 12-month futures avg ≥ $5.00/MMBtu | daily | MED |
| Henry Hub 12-month futures jumps ≥ 15% in 5 sessions | daily | HIGH |
| News RSS hit on the bottleneck query | hourly | MED |

**Baseline:** EIA's December 2025 Short-Term Energy Outlook projected 2026 Henry Hub averaging **$4.01/MMBtu** (S&P Global, Dec 9, 2025: *"The agency forecast Henry Hub natural gas prices would average … $4.01/MMBtu in 2026"*); the **January 2026 STEO subsequently revised this down to "just under $3.50 per million British thermal units (MMBtu)"** per EIA Today in Energy. We therefore set $5.00 as a "stress" line — substantially above either revision — and flag jumps from there. Front-month was $4.875/MMBtu in late January 2026 per EIA Natural Gas Weekly, indicating the strip was already running tight versus EIA's annual average forecast.

**XLSX parsing snippet:**
```python
# lib/grid_queues.py
import pandas as pd, requests, hashlib
HEADERS = {"User-Agent": "catalyst-tracker your.email@example.com"}

def pjm_active_queue() -> pd.DataFrame:
    url = "https://services.pjm.com/PJMPlanningApi/api/Queues/ExportToExcel"
    r = requests.get(url, headers=HEADERS, timeout=60); r.raise_for_status()
    return pd.read_excel(r.content)

def caiso_queue() -> pd.DataFrame:
    url = "https://www.caiso.com/documents/publicqueuereport.xlsx"
    r = requests.get(url, headers=HEADERS, timeout=60); r.raise_for_status()
    return pd.read_excel(r.content)

def ercot_gis_latest_url() -> str:
    # Scrape https://www.ercot.com/gridinfo/resource for newest GIS_REPORT link
    ...
```

---

### CATALYST 6 — Memory/Storage Price Stress
**Module:** `catalysts/c6_memory.py`
**Cadence:** Twice hourly (news-driven, same substrate as C3).

**Thesis:** Memory/storage contract prices are the upstream thermometer of the
AI-capex buildout. In the 2018 and 2022 cycles, memory price peaks led
hyperscaler capex cuts by one to two quarters. The 2025–2026 DRAM/NAND
super-spike is the froth; the rollover, when it comes, is the signal.

**Data sources:** Google News RSS queries (TrendForce, DigiTimes, and the
financial press all flow through it):
- `%22DRAM%22+price+when:1d`
- `%22NAND%22+price+when:1d`
- `%22HBM%22+OR+%22memory+chip%22+price+when:1d`
- `%22SSD%22+OR+%22HDD%22+OR+%22hard+drive%22+price+when:1d`

**Trigger conditions:**

| Signal | Logic | Severity |
|---|---|---|
| Order unwind | cancel orders / inventory write-down / capex cut near a memory-subject mention | CRITICAL |
| Price reversal | price cut/fall/drop/slump, oversupply, glut, inventory correction near subject | HIGH |
| Price surge (froth) | price hike/surge/spike, shortage, allocation, record high, double-booking near subject | MED |

All tokens must appear within 120 chars of a memory-subject term
(DRAM/NAND/HBM/DDRx/flash memory/memory chip/SSD/HDD/hard drive).
Consumer-deal headlines (Black Friday, Prime Day, deals/discount/coupon)
are rejected outright.

**Example alert subjects:**
- `[C6-HIGH] DRAM contract prices fall 10% as oversupply emerges`
- `[C6-CRITICAL] Hyperscaler cancels NAND orders amid capex rethink`

---

### CATALYST 7 — Credit Market Stress
**Module:** `catalysts/c7_credit.py`
**Cadence:** Twice hourly (daily FRED series, cheap to poll).

**Thesis:** The AI buildout has shifted from an equity story to a debt story, and
bubbles tear open in the credit market before equities. Corporate spreads are at
their tightest since 1997 — the market prices almost no risk. The signal is not
the tight level but spreads STARTING to widen. The "fuse of fuses".

**Data sources (FRED keyless CSV, `fredgraph.csv`):**
- `BAMLH0A0HYM2` — ICE BofA US High-Yield Index OAS
- `BAMLC0A0CM` — ICE BofA US Corporate (IG) Index OAS

**Trigger conditions (computed in-memory over the fetched series):**

| Signal | Logic | Severity |
|---|---|---|
| SPREAD_WIDENING | current OAS − trailing-90-session low ≥ trigger (HY +75bp, IG +30bp) | MED (HIGH at 2×) |
| SPREAD_STRESS | current OAS ≥ absolute level (HY 400bp, IG 125bp) | HIGH |

---

### CATALYST 8 — Macro Triggers (inflation / Fed path)
**Module:** `catalysts/c8_macro.py`
**Cadence:** Daily (CPI is monthly; daily poll catches the print promptly).

**Thesis:** Inflation sticks → the Fed can't cut → high valuations and leverage are
squeezed together. Cheap money is the common fuel of every signal in this tracker.

**Data source:** `CPIAUCSL` (CPI all-urban, monthly index) via FRED keyless CSV.

**Trigger conditions:**

| Signal | Logic | Severity |
|---|---|---|
| CPI_HOT | YoY ≥ 3.5% | MED (HIGH at ≥ 4.5%) |
| CPI_REACCEL | YoY rises 2 consecutive months AND ≥ 3.0% | MED |

---

### CATALYST 9 — Crypto Cycle Top
**Module:** `catalysts/c9_crypto.py`
**Cadence:** Daily.

**Thesis:** Bitcoin runs on the same risk appetite and cheap-money liquidity as the
AI-equity complex. An over-extended BTC is cross-asset confirmation of late-cycle
risk-on positioning.

**Data source:** CoinGecko public API (keyless), daily BTC closes.

**Trigger conditions:**

| Signal | Logic | Severity |
|---|---|---|
| MAYER_HOT | Mayer Multiple (price / 200DMA) ≥ 2.4 | MED (HIGH at ≥ 2.8) |
| PI_CYCLE_TOP | 111DMA crosses above 2× 350DMA | HIGH |

---

## 4. Scheduling Design

| Workflow | Cron (UTC) | Reason |
|---|---|---|
| `catalyst1_depreciation.yml` | `0 11 * * *` + `0 */2 * * 1-5` during earnings windows | 10-K/10-Q filings cluster 4–6 weeks after quarter-ends |
| `catalyst2_neoclouds.yml` | `30 13-21 * * 1-5` + `0 12 * * 0,6` | Hourly during US market; less on weekends |
| `catalyst3_openai.yml` | `*/30 * * * *` | News-driven, time-sensitive |
| `catalyst4_capex.yml` | `30 11 * * *` | Daily; earnings-week burst added dynamically by reading the previous run's "next earnings date" cache |
| `catalyst5_grid.yml` | `0 10 * * *` + `15 13 1-7 * 5` | Daily; ERCOT GIS first Friday of month |
| `dashboard_build.yml` | on `workflow_run` of any catalyst | Rebuild on every state change |
| `keepalive.yml` | `0 6 * * 1` | Avoid 60-day cron disablement |

GitHub Actions cron is not exact (10–30 min drift typical). For C3 (news), we therefore set 30-min cadence to ensure ≤45 min worst-case latency. For higher precision, add a free `cron-job.org` job hitting `POST /repos/{owner}/{repo}/actions/workflows/catalyst3_openai.yml/dispatches` with a fine-grained PAT.

---

## 5. Email Alerting

### Recommendation: **Gmail SMTP with App Password**
- ✅ Truly free, no card.
- ✅ 500 recipients/day from a personal Gmail (more than enough — we expect <10 alerts/day in normal periods).
- ✅ One-time setup: enable 2FA → create App Password at https://myaccount.google.com/apppasswords → store as `GMAIL_APP_PASSWORD` secret.
- ❌ Daily volume limit makes it bad for marketing blasts; fine for ops alerts.

**Alternatives considered:**
- AWS SES: free tier 200 emails/day, but only when sending from EC2/Lambda from a verified domain — adds setup friction.
- SendGrid free: 100/day, requires phone verification, sender authentication, account in good standing.

### Implementation (`lib/notify.py`):
```python
import os, smtplib, hashlib
from email.message import EmailMessage
from lib.state import State

def send_alert(subject: str, body: str, severity: str = "MED"):
    st = State("notify")
    fp = hashlib.sha256(f"{subject}|{body[:500]}".encode()).hexdigest()
    if st.seen("alerts_dedup", fp, ttl_seconds=86400 * 7):
        return False  # already sent in last 7 days
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ["GMAIL_USER"]
    msg["To"] = os.environ["ALERT_TO"]
    msg.set_content(body)
    msg.add_header("X-Catalyst-Severity", severity)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)
    st.mark_seen("alerts_dedup", fp)
    return True
```

**Severity routing:** subject line begins with `[C{N}-{SEVERITY}]`. Users can build Gmail filters like `subject:[C2-CRITICAL]` → forward to phone via Gmail's mobile push.

---

## 6. State / Persistence

**Recommended: SQLite committed back to repo** + `actions/cache` for warm reads.

```
state/tracker.sqlite   (committed; ~1–10 MB after a year)
```

**Schema (minimum):**
```sql
CREATE TABLE seen (table_name TEXT, key TEXT, ts INTEGER, PRIMARY KEY(table_name, key));
CREATE TABLE c1_filings (cik TEXT, accession TEXT PRIMARY KEY, form TEXT, filed_date TEXT, hits_json TEXT);
CREATE TABLE c2_metrics (ticker TEXT, ts INTEGER, close REAL, volume INTEGER, short_interest REAL);
CREATE TABLE c2_bonds (cusip TEXT, ts INTEGER, price REAL, yield REAL);
CREATE TABLE c3_baselines (key TEXT PRIMARY KEY, value REAL, ts INTEGER);
CREATE TABLE c3_news (guid TEXT PRIMARY KEY, feed TEXT, title TEXT, link TEXT, ts INTEGER, severity TEXT);
CREATE TABLE c4_xbrl (cik TEXT, concept TEXT, period TEXT, val REAL, PRIMARY KEY(cik, concept, period));
CREATE TABLE c4_transcripts (ticker TEXT, quarter TEXT PRIMARY KEY, url TEXT, hits_json TEXT);
CREATE TABLE c5_queues (iso TEXT, snapshot_date TEXT, total_mw REAL, withdrawn_count INT, PRIMARY KEY(iso, snapshot_date));
CREATE TABLE alerts_sent (id INTEGER PRIMARY KEY, fp TEXT UNIQUE, ts INTEGER, subject TEXT);
```

**Workflow pattern:**
```yaml
- uses: actions/checkout@v4
- uses: actions/cache@v4
  with:
    path: state/tracker.sqlite
    key: tracker-state-${{ github.run_id }}
    restore-keys: tracker-state-
- run: python -m catalysts.c1_depreciation
- name: Commit state
  uses: stefanzweifel/git-auto-commit-action@v5
  with:
    file_pattern: state/tracker.sqlite docs/data/status.json
    commit_message: "state: c1 run ${{ github.run_id }}"
```

This gives us git history of every state change (useful for forensics on missed alerts) while keeping reads fast via cache.

---

## 7. Dashboard

Static HTML in `docs/index.html`, regenerated by `scripts/build_dashboard.py` after every catalyst run. GitHub Pages publishes from `docs/` on the `main` branch.

**Sections:**
1. Header: green/yellow/red status per catalyst, last-run timestamp.
2. Catalyst 1: table of latest filings scanned per company + any active hits.
3. Catalyst 2: spark-line of close prices, bond price column, going-concern flag column.
4. Catalyst 3: 30-day OpenAI news feed table; current ARR/burn baselines.
5. Catalyst 4: TTM Capex/OCF chart per hyperscaler; latest transcript regex hits.
6. Catalyst 5: Queue MW history per ISO, Henry Hub 12-month curve.
7. Footer: link to alerts log, GitHub Actions runs.

Render with Jinja2 → plain HTML + a single `data/status.json`. Use Chart.js via CDN (no build step). Total page weight <500 KB.

URL after deploy: `https://{user}.github.io/catalyst-tracker/`.

---

## 8. Setup Instructions

### One-time
1. **Fork or create the repo** as **public** (`catalyst-tracker`).
2. **Enable GitHub Actions** (Settings → Actions → "Allow all actions").
3. **Enable GitHub Pages** (Settings → Pages → Source: "Deploy from a branch", branch `main`, folder `/docs`).
4. **Get free API keys (no card):**
   - EIA: https://www.eia.gov/opendata/register.php → email-only signup → `EIA_API_KEY`.
   - FRED: https://fredaccount.stlouisfed.org/apikeys → `FRED_API_KEY`.
5. **Gmail App Password:**
   - Enable 2-Step Verification on your Google account.
   - Visit https://myaccount.google.com/apppasswords, app name "catalyst-tracker", copy the 16-char password.
6. **Add repo Secrets** (Settings → Secrets and variables → Actions → New repository secret):
   - `GMAIL_USER` — `you@gmail.com`
   - `GMAIL_APP_PASSWORD` — 16-char app password (no spaces)
   - `ALERT_TO` — destination address
   - `EIA_API_KEY`, `FRED_API_KEY`
   - `SEC_USER_AGENT` — `catalyst-tracker you@example.com` (SEC requires real contact)
7. **Add repo Variables** (non-secret config): `WATCHLIST_OVERRIDE` (optional JSON to extend tickers).

### First deploy
```bash
git clone https://github.com/{you}/catalyst-tracker
cd catalyst-tracker
pip install -r requirements.txt
python scripts/backfill.py --catalyst all --days 365   # seeds historical state, ~5–10 min
git add state/ && git commit -m "initial state seed" && git push
# trigger first runs manually
gh workflow run catalyst1_depreciation.yml
gh workflow run catalyst5_grid.yml
```

### Test path
```bash
python scripts/test_alert.py            # sends a test email
pytest tests/test_regex.py -v           # validates regex against fixture filings
python -m catalysts.c1_depreciation --dry-run --since 2025-01-01
```

`--dry-run` prints what would be emailed without sending.

---

## 9. Specific URLs / Endpoints (Reference Card)

| Source | URL |
|---|---|
| SEC submissions JSON | `https://data.sec.gov/submissions/CIK{cik10}.json` |
| SEC company facts (XBRL) | `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json` |
| SEC company concept | `https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/{concept}.json` |
| SEC EDGAR full-text search | `https://efts.sec.gov/LATEST/search-index?q={query}&forms=10-K,10-Q&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD` |
| SEC company filings RSS | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-Q&output=atom` |
| SEC ticker→CIK map | `https://www.sec.gov/files/company_tickers.json` |
| FINRA bond search | `https://www.finra.org/finra-data/fixed-income/corp-and-agency` |
| FINRA bond detail | `https://www.finra.org/finra-data/fixed-income/corporate-bond-detail/{symbol}` |
| PJM queue export | `https://services.pjm.com/PJMPlanningApi/api/Queues/ExportToExcel` |
| ERCOT GIS landing | `https://www.ercot.com/gridinfo/resource` |
| ERCOT GIS report list | `https://mis.ercot.com/misapp/GetReports.do?reportTypeId=15933` |
| CAISO public queue | `https://www.caiso.com/documents/publicqueuereport.xlsx` |
| EIA API | `https://api.eia.gov/v2/seriesid/{series_id}?api_key={KEY}` |
| FRED API | `https://api.stlouisfed.org/fred/series/observations?series_id={id}&api_key={KEY}&file_type=json` |
| Motley Fool transcripts | `https://www.fool.com/earnings-call-transcripts/` |
| WSJ Tech RSS | `https://feeds.content.dowjones.io/public/rss/RSSWSJD` |
| WSJ Business RSS | `https://feeds.content.dowjones.io/public/rss/RSSBusinessNews` |
| Bloomberg Tech RSS | `https://feeds.bloomberg.com/technology/news.rss` |
| Google News RSS query | `https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en` |
| Yahoo Finance (via yfinance) | (no URL; library) |
| Nasdaq short interest | `https://www.nasdaq.com/market-activity/stocks/{ticker}/short-interest` |

**SEC rate limit:** ≤10 req/s, with `User-Agent` header containing real contact info, or your IP is blocked. We rate-limit at 5 req/s.

---

## 10. Alert Trigger Logic — Exact Conditions

### C1 Depreciation
> **IF** new 10-K/10-Q filing for any of {MSFT, GOOGL, META, AMZN, ORCL, NVDA} (detected via SEC submissions JSON polling) **AND** filing text matches any of the 9 regex patterns in §3-C1 **THEN** send email subject `[C1-{SEV}] {TICKER} {FORM}: depreciation language change` with body containing matched snippet (±240 chars), filing URL, and accession number.

### C2 Neocloud Distress
> **IF** (new 10-K/10-Q matches `going concern OR material adverse OR covenant breach OR covenant default`) **OR** (new 8-K with item 2.04 / 4.02 / 1.03) **OR** (1-day stock close ≤ –15% AND volume ≥ 3× 20-day avg) **OR** (latest bond trade < 90 cents on dollar) **OR** (short interest ≥ 20% of float) **OR** (RSS hit containing `{ticker} downgrade` from S&P/Moody's feed) **THEN** alert with severity per §3-C2 table.

### C3 OpenAI Stress
> **IF** any monitored RSS feed item OR any new MSFT 10-Q/10-K paragraph contains a token from the OpenAI keyword set (§3-C3) **AND** SHA-256 of (title + first 200 chars) not in `c3_news` table for last 30 days **THEN** alert. **ALSO IF** extracted numeric burn-rate metric increases >25% QoQ vs `c3_baselines` **THEN** alert HIGH.

### C4 Capex Cuts
> **IF** TTM(Capex)/TTM(OCF) for any hyperscaler crosses 110% upward (vs prior quarter's value in `c4_xbrl`) **OR** new transcript matches `(more disciplined|moderating|tempered|slower pace).{0,60}(capex|capital|spend|invest)` **OR** matches `(reduc|cut|lower|trim).{0,30}(202[6-9]) capital` **OR** TTM FCF turns negative **THEN** alert.

### C5 Grid Bottlenecks
> **IF** PJM queue snapshot diff vs 7-days-ago shows ≥ 5 new "Withdrawn" status changes for ≥100 MW projects **OR** ERCOT total active MW drops ≥ 5% MoM **OR** CAISO ≥ 3 large-load suspensions in latest cycle **OR** any utility 8-K matches `power\s+delay|grid\s+bottleneck|interconnection\s+delay|data\s+center.{0,40}delay` **OR** EIA Henry Hub 12-month strip avg ≥ $5.00 **OR** that strip jumps ≥ 15% in 5 sessions **OR** Google News bottleneck-query feed item is new **THEN** alert.

### C6 Memory/Storage Price Stress
> **IF** a new RSS item pairs a memory-subject term (`dram|nand|hbm|ddr[3-5]|flash memory|memory chip|memory price|ssd|hdd|hard drive`) with a tier token within 120 chars — order-cancellation/write-down/capex-cut (CRITICAL), price-reversal/oversupply/glut (HIGH), or price-surge/shortage/allocation (MED) — **AND** the item contains no consumer-deal noise terms **THEN** alert.

### C7 Credit Market Stress
> **IF** HY or IG OAS (FRED) has widened ≥ trigger bp off its trailing-90-session low (HY +75bp / IG +30bp) **OR** the OAS is ≥ its absolute stress level (HY 400bp / IG 125bp) **THEN** alert.

### C8 Macro Triggers
> **IF** CPI YoY ≥ 3.5% **OR** CPI YoY has risen for two consecutive months and is ≥ 3.0% **THEN** alert.

### C9 Crypto Cycle Top
> **IF** BTC Mayer Multiple (price/200DMA) ≥ 2.4 **OR** the 111DMA crosses above 2× the 350DMA (Pi Cycle Top) **THEN** alert.

---

## 11. Risk Management

**False positives:**
- Each catalyst has a `tests/fixtures/` folder with **real filing snippets that should match** and **decoy snippets that should NOT match** (e.g., generic "useful life" text in totally unrelated PP&E discussion). CI runs `pytest` on every push.
- For text-based triggers, require ≥1 specific anchor token (e.g., "server", "network", "GPU", "property and equipment") within 80 characters of the generic phrase.
- For news (C3), require **two** of the keywords or **one** CRITICAL-tier keyword to fire — single mentions of "Sarah Friar" alone are MED only.

**Deduplication:**
- All alerts hashed by `SHA-256(subject + body[:500])`, stored in `alerts_sent` with TTL 7 days. Same alert won't re-fire within a week.
- News items dedup'd by `(feed_url, guid)` and by content hash for items with unstable GUIDs.
- SEC filings dedup'd by accession number (immutable).

**Rate limiting:**
- SEC: token bucket at 5 req/s, 150 ms minimum spacing, `User-Agent` always set.
- yfinance: 2 req/s, 10-second backoff on `429` (rare).
- FINRA: 1 req/s (HTML scrape, conservative).
- News RSS: cache `Last-Modified` / `ETag` headers; only fetch if changed.
- Tenacity retry on 5xx and ConnectTimeout: 3 attempts, exponential backoff 2/4/8 s.

**Error handling:**
- Each catalyst's `run()` is wrapped in a top-level `try/except`; on failure it sends a `[OPS-ERROR]` email with traceback and continues to the next catalyst (one bad source must not block others).
- Workflow uses `continue-on-error: true` per catalyst step plus a final aggregator step that fails the run only if **all** catalysts errored — that surfaces an obvious red ❌ on the dashboard.
- Dead-feed detection: if a feed has returned 0 new items for 14 days, send `[OPS-WARN]` email — likely the feed URL changed.

**Schema migrations:** `lib/state.py` runs `PRAGMA user_version` checks and applies forward-only SQL migrations from `state/migrations/*.sql` on startup.

---

## 12. Extensibility

To add a 6th catalyst:
1. Create `catalysts/c6_yourname.py` subclassing `CatalystBase`.
2. Implement `run() -> list[Alert]`.
3. Add tables to `state/migrations/00X_add_c6.sql`.
4. Add `.github/workflows/catalyst6_yourname.yml` (copy any existing one).
5. Register in `scripts/build_dashboard.py` (`CATALYSTS = [..., "c6"]`).

`CatalystBase` ABC provides standardized: `Alert` dataclass, `send()`, dedup, severity enum, `--dry-run` flag, structured JSON logging. Adding a catalyst is ~50–100 lines of code plus a YAML file.

For multi-tenancy / new tickers: add entries to `lib/config.py`'s `WATCHLISTS` dict — no code changes needed for C1/C2/C4 to pick them up.

---

## Recommendations (Build Order & Thresholds That Would Change Them)

1. **Day 1 (90 min): Skeleton + C1 + Email.** Get repo, secrets, Gmail SMTP, `lib/edgar.py`, `lib/notify.py`, and `catalysts/c1_depreciation.py` working end-to-end against the Amazon FY2024 10-K fixture. This proves the whole loop.
2. **Day 1 (60 min): C2 Neoclouds.** Highest-information catalyst right now given CoreWeave/Applied Digital fragility (Applied Digital already disclosed going-concern language in its FY2025 Q3 10-Q before later "alleviating" it; CoreWeave amended covenants in Q4 2025 per their 8-K).
3. **Day 2 (90 min): C4 Capex** via XBRL — this is the one that converts pure number streams into alerts and tests the math layer.
4. **Day 2 (60 min): C3 OpenAI** RSS pipeline + dedup. Highest noise, so build it after the dedup layer is mature.
5. **Day 2 (60 min): C5 Grid** queue downloaders. Slowest-moving signal, so lowest urgency.
6. **Day 2 (45 min): Dashboard + keepalive.** Last because the underlying signals must work first.

**Thresholds that would change the architecture:**
- If you need **<5-min latency on news**, swap the GitHub Actions cron for an Oracle Cloud Always Free ARM VM running a Python daemon with apscheduler — same code, sub-minute scheduling.
- If alert volume routinely exceeds **30/day**, switch from Gmail SMTP to AWS SES (verified domain, $0.10/1000 emails after 200/day free tier).
- If state grows past **~50 MB**, move SQLite off git into a Cloudflare R2 free bucket (10 GB free) or an `actions/upload-artifact` snapshot rotation.
- If you need **historical TRACE replay**, FINRA's Academic dataset is available to universities for $500/yr setup; otherwise live-only delayed prices remain $0.

---

## Caveats

- **GitHub Actions cron drift** of 10–30 min is normal; don't expect minute-precision. For sub-15-min latency, layer in a free `cron-job.org` external trigger.
- **FINRA's free public bond display is delayed 4 hours** vs real-time; the real-time TRACE feed is **$1,500/month per data set** ($6,000/mo for all four corp/agency data sets) per FINRA's official pricing schedule. The 4-hour delay is fine for catalyst-style monitoring but won't catch intra-day distress moves.
- **SEC EDGAR full-text search can be slow** during heavy-filing periods (Feb, May, Aug, Nov). Build in 60-second timeouts and exponential backoff.
- **Earnings transcript scraping is fragile** — Motley Fool's HTML occasionally restructures; the SEC 8-K Item 2.02 attachment route is a more durable secondary source.
- **The Information's RSS** sometimes only shows headline (paywalled body); we treat it as an early-warning signal, not a quotable source.
- **News RSS feeds occasionally restructure URLs** (Reuters did in 2022, deprecating `feeds.reuters.com`). The `lib/rss.py` has a "feed-failed-for-N-days" health check that emails an `[OPS-WARN]`.
- **Henry Hub baseline shifts quickly.** EIA's December 2025 STEO forecast 2026 average at $4.01/MMBtu; the January 2026 STEO cut that to "just under $3.50/MMBtu." Re-anchor the $5.00 stress threshold against the latest STEO each quarter or alerts will become noisy.
- **Free-tier reliance**: GitHub announced March 2026 pricing changes that affect *self-hosted* runners; standard GitHub-hosted runners on **public** repos remain free. If that changes, the migration path is to Oracle Cloud Always Free (cron + persistent disk + SMTP all work the same; a single free-tier ARM VM runs everything for $0).
- **None of this is investment advice.** Catalysts are signals to investigate, not to trade. False-positive rate after tuning typically lands at 10–20% on text triggers; the system is designed to favor recall over precision because missed catalysts in a real bubble-stress event are far more costly than a few extra emails.
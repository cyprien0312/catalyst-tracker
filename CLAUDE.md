# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**短期记忆：[`docs/STATE.md`](docs/STATE.md)** —— 此刻状态和全部待办只在那一处。
**先读它再动手**；本文件只讲「怎么干」，不讲「现在怎么样」。

> ⚠️ **生产跑在另一台机器（openclaw）上，不是每台 clone 都在跑。**
> 动手前先 `git fetch && git status -sb` —— 本机 clone 落后几千个 `state:` commit 是常态，
> 拿本地 `state/tracker.sqlite` 当现状会得出完全相反的结论（2026-08-03 真踩过）。

## What this is

`catalyst-tracker` is a Python 3.11 monitoring pipeline that scans SEC filings, RSS feeds, XBRL financial data, ISO interconnection-queue snapshots, and macro/credit/crypto market data for eleven "AI infrastructure bubble-stress" signals (C1–C11) and emails alerts via the Resend HTTP API (`lib/email_send.py` — the Gmail SMTP path was replaced; `GMAIL_*` env vars are no longer used).

C11 (SpaceX IPO unlock / passive flows) is the single-name index-mechanics specimen: a deterministic lock-up tranche calendar (⚠️ dates estimated from the S-1-derived schedule — earnings-linked tranches shift; hardcoded in `UNLOCK_SCHEDULE`), Google News RSS with a proximity classifier (mission-coverage noise guard), and a daily ETF-holdings diff from issuer CSVs (default ARKQ; extend via `C11_ETF_CSVS="FUND=url,..."`). ETF leg stores baselines silently on first run (same transition semantics as C4/C5); emails floored to HIGH via `CATALYST_EMAIL_MIN_SEVERITY`.

C7 (credit spreads), C8 (CPI + core PCE) and C10 (broad-USD index + 10y real yield) pull from FRED's **keyless** `fredgraph.csv` export (`lib.fred.series_csv`) — no `FRED_API_KEY` needed. C9 uses the keyless CoinGecko public API (`lib.crypto`). All degrade to `[]` on fetch failure. C7/C8/C9/C10 compute their signals in-memory from the fetched series (transition logic doesn't depend on stored prior rows), so a fresh DB is NOT silent for them — unlike C4/C5. C10 mirrors C7's structure exactly (per-series config, trailing-90 low transition, MED→HIGH at 2× trigger). State lives in SQLite (`state/tracker.sqlite`); the dashboard is static HTML in `docs/` published to GitHub Pages.

Production deployment is **local cron on this host** (not GitHub Actions). The workflows in `.github/workflows/` have their `schedule:` blocks commented out — only `workflow_dispatch` and `tests.yml` are live. See README "Why a single host instead of GitHub Actions" for rationale (mainly: reusing the long-lived `claude` CLI session for free LLM explanations).

## Commands

```bash
# Setup
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# Tests
.venv/bin/pytest -v                          # all
.venv/bin/pytest tests/test_c4.py -v         # one file
.venv/bin/pytest -k "ratio_cross" -v         # match by name

# Run a catalyst (dry-run prints to stdout, no email, no state write of alerts)
.venv/bin/python -m catalysts.c1_depreciation --dry-run
.venv/bin/python -m catalysts.c2_neoclouds   --dry-run --no-prices
.venv/bin/python -m catalysts.c3_openai      --dry-run --no-edgar
.venv/bin/python -m catalysts.c5_grid        --dry-run --skip-iso  # offline-friendly
.venv/bin/python -m catalysts.c7_credit      --dry-run  # C7/C8/C9/C10 use keyless FRED/CoinGecko
.venv/bin/python -m catalysts.c8_macro       --dry-run  # CPI + core PCE
.venv/bin/python -m catalysts.c9_crypto      --dry-run
.venv/bin/python -m catalysts.c10_liquidity  --dry-run  # broad USD + 10y real yield
.venv/bin/python -m catalysts.c11_spacex     --dry-run  # SPCX unlock calendar + news + ETF holdings diff

# Verbosity
LOG_LEVEL=DEBUG .venv/bin/python -m catalysts.c3_openai --dry-run

# Daily digest email (priority-ordered heartbeat + LLM FOCUS analysis + buy plan)
.venv/bin/python scripts/daily_report.py --dry-run             # print
.venv/bin/python scripts/daily_report.py --html-out /tmp/d.html  # dump HTML
bin/send_daily_report.sh                                        # cron wrapper (sources env)

# Daily news roll-up email (the day's alert bodies + bilingual explanations, one mail)
.venv/bin/python scripts/news_report.py --dry-run               # print
.venv/bin/python scripts/news_report.py --hours 48              # widen the window
.venv/bin/python scripts/news_report.py --html-out /tmp/n.html  # dump HTML
bin/send_news_report.sh                                         # cron wrapper (09:10)

# NDX buy-plan signal (regime + drawdown ladder, keyed off the C7/C2 fuses)
.venv/bin/python scripts/regime_signal.py          # print the plan
.venv/bin/python scripts/regime_signal.py --json   # machine-readable

# Rung/regime-flip alerter (hourly cron at :53 via bin/check_rungs.sh)
.venv/bin/python scripts/rung_alert.py --dry-run   # print would-be alerts, no email/state

# Dashboard rebuild (writes docs/index.html, docs/thresholds.html, docs/data/status.json)
.venv/bin/python scripts/build_dashboard.py

# Knowledge base (verify stage): publish catalyst trigger facts into the shared
# Obsidian corpus at ~/ObsidianVault/knowledge/ai-infra/ (idempotent; respects manual notes)
.venv/bin/python -m scripts.sync_knowledge --dry-run   # preview (static trigger thresholds)
.venv/bin/python -m scripts.sync_knowledge             # write
# fetch+verify: pull live readings (FRED/CoinGecko/EIA) through a plausibility gate, write live-* notes
.venv/bin/python -m scripts.fetch_knowledge --dry-run  # fetch + verify, write nothing
.venv/bin/python -m scripts.fetch_knowledge            # refresh live readings
bin/refresh_knowledge.sh                               # cron wrapper (08:45 daily): sync + fetch; read-only vs repo

# Smoke tests before prod changes
.venv/bin/python scripts/llm_smoke.py     # verifies `claude` CLI envelope still matches lib/llm.py parsing
.venv/bin/python scripts/test_alert.py    # sends an [OPS-TEST] email via Resend

# Inspect state
sqlite3 state/tracker.sqlite ".tables"
sqlite3 state/tracker.sqlite ".schema c4_xbrl"
sqlite3 state/tracker.sqlite "SELECT ts, catalyst, severity, subject FROM alerts ORDER BY ts DESC LIMIT 20"
```

For real runs, secrets must be loaded from `~/.catalyst.env` (outside the repo) — at minimum `SEC_USER_AGENT`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_TO`. `set -a; source ~/.catalyst.env; set +a` before invoking.

## Architecture

### Module shape

Each `catalysts/cN_*.py` is a standalone module exposing a class (subclass of `catalysts.base.CatalystBase`) plus `__main__` glue via `catalysts.base.run_cli`. The CLI parses `--dry-run` and catalyst-specific flags, instantiates the catalyst, calls `run() -> list[Alert]`, then either prints or emails. **Adding a new flag means passing an `extra_args` callable to `run_cli`** — see `c2_neoclouds.py` for the pattern.

`Alert` (`catalysts/base.py`) is a frozen dataclass `(catalyst, severity, subject, body)` with severity validated against `("LOG", "MED", "HIGH", "CRITICAL")`.

### Shared infrastructure (`lib/`)

- `lib/edgar.py` — SEC EDGAR client (requires `SEC_USER_AGENT`)
- `lib/filing_context.py` — **sentence-level context gate for the C1/C2 filing-text regexes.**
  The patterns match vocabulary, not disclosures: every 10-Q carries accounting-policy
  boilerplate ("Estimates are used for, but not limited to, … impairment of property and
  equipment …") and risk-factor hypotheticals ("… debt covenant defaults …, **could** have
  a material adverse effect") built from exactly the words of the real event. `scan()` is
  the entry point both `c1_depreciation.scan_text` and `c2_neoclouds.scan_text` delegate to.
  Verdict per hit: `BOILERPLATE` ⇒ drop; else `AFFIRMATIVE` ⇒ keep; else `HYPOTHETICAL` ⇒ drop;
  else keep. It **fails open** on purpose — a suppressed real signal is silent, so it is the
  more expensive error. Per-pattern subject checks live in each catalyst's `REQUIRES` dict.
- `lib/rss.py` — feedparser wrapper, idempotent on `(feed_url, GUID)` with 30-day TTL
- `lib/xbrl.py` — XBRL facts pull for hyperscaler capex/OCF/FCF (C4)
- `lib/grid_queues.py` — PJM/CAISO interconnection queue XLSX parsers (C5). PJM is now a POST to `services.pjm.com/PJMPlanningApi/api/Queue/ExportToXls` with an `api-subscription-key` header (the old GET `/Queues/ExportToExcel` 404s as of 2026-05). The subscription key lives in the public JS bundle on pjm.com and may rotate — if PJM fetches start 401/403'ing, refresh `PJM_API_SUBSCRIPTION_KEY` from `https://www.pjm.com/dist/interconnectionqueues.*.js`.
- `lib/eia.py` — Henry Hub strip (C5). `lib/fred.py` — FRED data: `observations()` (JSON API, needs `FRED_API_KEY`) and **`series_csv()`** (the keyless `fredgraph.csv` export, used by C7 credit spreads + C8 CPI so they work with no secret).
- `lib/crypto.py` — CoinGecko public API (keyless) — `btc_daily_closes()` daily BTC closes for C9. Rate-limited; degrades to `[]`.
- `lib/prices.py` — yfinance wrapper with **6-hour TTL cache** keyed in the `c2_price_check` table (yfinance throttles hard)
- `lib/state.py` — SQLite layer; tables include `c4_xbrl`, `c5_queues`, `c7_spreads`, `c8_macro`, `c9_crypto`, `c10_liquidity`, `llm_cache`, `alerts` (history rendered in dashboard), and the dedup `seen` table (`alerts_dedup` namespace + per-source idempotency keys)
- `lib/notify.py` — Resend send + alert dedup + persistence. **SHA-256 over `(subject, body[:500])` with 7-day TTL** prevents repeat emails AND prevents duplicate `alerts` rows. Every non-deduped alert is INSERTed into the `alerts` table regardless of whether SMTP fired. Two email-mute controls: `CATALYST_EMAIL_DISABLE=c3,c5` (CSV) silences a catalyst's emails entirely; `CATALYST_EMAIL_MIN_SEVERITY=c6:HIGH` (CSV of `tag:floor`) emails only alerts at/above the floor for that catalyst (quieter ones persist but don't email). The per-catalyst floor takes precedence over the blanket disable list. Both keep rows in DB; header `X-Catalyst-Severity:` still set.
- `lib/thresholds.py` — numeric thresholds (110% capex/OCF, $5/MMBtu Henry Hub, etc.). When tuning email volume, change here rather than in catalyst modules.
- `lib/explanations.py` — `_REGISTRY` of static English "What this means / Why it matters" templates keyed by `(catalyst, signal_kind)`. `append_context()` is the entry point that catalysts call; it bridges to the LLM layer when enabled.
- `lib/llm.py` — invokes local `claude` CLI in headless mode (`claude -p ... --model <m> --output-format json`) for bilingual EN/中文 explanations. **Passes `--model` explicitly (`CATALYST_LLM_MODEL`, default `claude-opus-4-8`)** — the CLI's own default (Fable 5) is region-restricted and returns `is_error="... Fable 5 is currently unavailable"` (e.g. AU), which silently forces the static-template fallback. `freeform(prompt)` is a public entry point for free-form text (used by the daily-digest FOCUS). Cache key includes `_PROMPT_VERSION` and the model tag — **bumping `_PROMPT_VERSION` invalidates every cached explanation**. When `lib/knowledge.py` injects ai-infra facts, a digest of that block is folded into the cache key **only if facts are present**, so the no-knowledge path keeps its pre-existing cache namespace (no mass invalidation). Designed to never break alerting: any failure logs `llm.fallback reason=...` and returns `None`, caller uses static template.
- `lib/knowledge.py` — bridge to the **unified Obsidian knowledge base** (`~/ObsidianVault/knowledge/`, the cross-project corpus shared with aocai-studio et al.; override `CATALYST_KNOWLEDGE_DIR`). Domain `ai-infra` (override `CATALYST_KNOWLEDGE_DOMAIN`). **Read:** `facts_for_prompt(catalyst=, ticker=)` loads `.md` notes (YAML front-matter), filters by catalyst tag (exact, so `c1`≠`c10`) / ticker / keyword, and renders a compact block injected into the LLM prompts in `lib/llm.py` (per-alert, catalyst-filtered) and `scripts/daily_report.py` FOCUS (whole corpus). **Write (verify stage):** `write_fact()` persists a `generated: verify-auto` note — idempotent (overwrites the note sharing the same primary source URL in place) and **never clobbers** a hand-curated note (`manual: true`, or simply no `generated:` marker). Mirrors `lib/llm.py`: never raises — missing dir ⇒ read returns `[]`, write is a logged no-op. Drive the writer with `scripts/sync_knowledge.py`.
- `lib/knowledge_fetch.py` — **fetch + verify** companion: pulls the *live numeric readings* behind the thresholds (HY/IG OAS, CPI + core PCE, broad USD, 10y real yield, BTC Mayer Multiple, NDX drawdown, Henry Hub strip) from the same keyless FRED/CoinGecko/EIA sources the catalysts use, and writes them as dated, sourced `live-*` notes (tagged `live` + the catalyst) into `ai-infra`. "Verify" = a two-part gate per probe: authoritative source **and** finite + inside a plausibility band; a probe that fails either yields `None` and is **not written** (last good reading stays — never poisons the corpus with a bad/stale datum). All probe fetchers are injectable for tests. Drive with `scripts/fetch_knowledge.py`. So a catalyst's prompt now gets both the *rule* (from `sync_knowledge`) and the *current value* (from `fetch_knowledge`).
- `lib/log.py` — `get_logger(__name__)`; auto-attaches stack traces in `except` blocks. `LOG_LEVEL` env var controls level (default `INFO`).

### Transition semantics — critical for C4/C5

C4 and C5 numeric alerts fire on **transitions, not on persistent state**. C4 ratio-cross requires prior quarter < 110% and current ≥ 110%; FCF-negative requires prior ≥ 0 and current < 0. C5 MW-drop / new-withdrawals require a prior snapshot.

**Consequence:** the first scan against a fresh `state/tracker.sqlite` is intentionally quiet — it establishes baselines in `c4_xbrl` / `c5_queues`. When writing tests or debugging silence, check whether the prior row exists.

Dedup is per-`(signal_kind, ticker, period)` on top of the 7-day subject/body hash, so a one-time cross emits exactly one email forever (until the database is wiped).

### Dashboard alert viewer

`scripts/build_dashboard.py` renders the last 200 rows of the `alerts` table into `docs/index.html` with catalyst/severity filters and an "only unread" toggle. Read-state is tracked in browser `localStorage` under key `catalyst-tracker:read-ids` (per-device, not synced — there is no server-side write path because Pages is static). The Jinja templates use `Environment(autoescape=select_autoescape(["html","htm","xml"]))` because subjects/bodies originate from external RSS feeds — do NOT switch back to `Template(...)` without autoescape. Muted alerts (those whose catalyst is in `CATALYST_EMAIL_DISABLE`) get a `· muted` suffix in the summary row so they're visually distinct.

### Recovering from a polluted dedup state

If a noisy catalyst floods email (the original motivation for `CATALYST_EMAIL_DISABLE`), recovery is two steps: (1) add the catalyst tag to `CATALYST_EMAIL_DISABLE` in `~/.catalyst.env`; (2) optionally purge `alerts_dedup` so dashboard backfills with recent alerts (`DELETE FROM seen WHERE table_name='alerts_dedup'` via `State("x").connection()`). Purging only widens what enters `alerts` — it does NOT undo email mute. Per-source idempotency rows (filing accession numbers, RSS GUIDs, C4/C5 transition keys) are stored under different `table_name` values and should NOT be purged unless you want to re-emit historical signals.

### Cron wrapper (`bin/run_catalyst.sh`)

After `python -m catalysts.<module>` and `scripts/build_dashboard.py`, the wrapper **commits and pushes** `state/tracker.sqlite` + `docs/index.html` + `docs/thresholds.html` + `docs/data/status.json` to `origin/main` with `pull --rebase` retries (the catalysts cron-fire minutes apart but races still happen). Commits are authored `catalyst-bot <bot@openclaw.local>`; recent `state: ...` commits in `git log` are from cron, not human edits — don't revert them. `tests.yml` uses `paths-ignore` so these state commits don't burn CI.

### Daily digest (`scripts/daily_report.py`, `bin/send_daily_report.sh`)

A once-a-day heartbeat email (cron 09:00 local), separate from the per-alert path. Priority-ordered (C7→C2→C4→C1→C8→C6→C3→C5→C9, grouped fuses→hard-data→background→lagging). Numeric gauges (C7/C8/C9) are **re-fetched live** each run so the digest is current regardless of cron timing; C4 reads the latest `c4_xbrl` snapshot; event-driven catalysts roll up the `alerts` table (7-day window). The **FOCUS** note is written by `llm.freeform` (Opus) with a rule-based `_analytical_focus` fallback that bakes in per-signal cross-references (e.g. Oracle = Leopold's short / CDS +310% / the C7-repricing tell). **Repeat guard:** the last 5 FOCUS titles (stored in the `seen` table, namespace `focus_history`, key `YYYY-MM-DD|title`) are injected into the prompt with a "don't retell a recent angle when the state is flat" instruction — the LLM has no memory across runs, so without this it re-picks the same standing story every day. Titles are recorded on real sends only (`--dry-run` doesn't write). Multipart email (HTML + plain-text); no dedup — sends every day. The wrapper sources `~/.catalyst.env` but does **not** commit/push; its only state write is the `focus_history` row, swept into git by the :30-cadence catalyst runs (same as rung_alert). Pure helpers are unit-tested in `tests/test_daily_report.py` (loaded via importlib since the script lives in `scripts/`).

The digest also embeds a **BUY PLAN** card (`scripts/regime_signal.py`) just under FOCUS: a drawdown ladder for accumulating the **whole ETF portfolio** (IVV/BGBL core + satellites — NDX is the *trigger*, being the highest-beta AI tell, not the instrument). `lib/index_quote.py` pulls live NDX + SPX levels and ATHs via the keyless FRED `NASDAQ100`/`SP500` series; SPX renders as a reference line only (IVV/BGBL draws down shallower — NDX -20% ≈ SPX -13..-15%). The plan has two regimes, and **only the C7/C2 fuses flip between them** (all other signals are thermometers): **Regime A** (no fuse FIRING) = deep-heavy ladder (0%:10 / -10%:10 / -15%:15 / -20%:25), max 60% deployed / 40% reserve, "buy speed"; **Regime B** (C7 credit OR C2 neocloud FIRING) = freeze the fast ladder, deep ladder for a multi-quarter bust, last rung needs a manual stabilisation check (C7 stops widening, or 4-6wk no new 20d-low). Ladder rungs live in `REGIME_A_LADDER`/`REGIME_B_LADDER` in `scripts/regime_signal.py`. The card degrades to absent if the index fetch fails (wrapped in try/except in `build()`). Tested in `tests/test_regime_signal.py`.

**Rung/regime-flip alerter** (`scripts/rung_alert.py`, hourly cron at :53 via `bin/check_rungs.sh`): emails within the hour when NDX crosses a ladder rung (HIGH) or the A/B regime flips (A→B CRITICAL, B→A MED), instead of waiting for the 09:00 digest. A rung alerts **once per drawdown episode** — the idempotency key includes the ATH date (`seen` namespace `buyplan_rungs`), and the ATH only moves while no rung is triggered, so a recovery to a new high re-arms the ladder; the 0% starter rung never alerts. Last-known regime lives in `seen` namespace `buyplan_regime` (first run records it silently). Alerts flow through `lib/notify.send_alert` under tag `buyplan`, so they land in the `alerts` table/dashboard like any catalyst. The wrapper writes only `state/tracker.sqlite` and does not commit — the :30-cadence catalyst runs sweep the state change into git. Tested in `tests/test_rung_alert.py`.

### Daily news roll-up (`scripts/news_report.py`, `bin/send_news_report.sh`)

The companion to the digest, cron **09:10** (10 minutes after it). The digest answers *"what is
the state of the eleven signals"*; this answers *"what actually came in today"* — every alert from
the last 24h with its full body **and** its bilingual LLM explanation, grouped by catalyst in the
same priority spine, so the per-alert e-mails can stay muted without losing content.

- **Reads the `alerts` table only.** No feed re-fetch, no state write at all (not even a `seen`
  row — unlike the digest's `focus_history`). Safe to re-run, safe to run out of order with the
  catalysts, and it never dirties `state/tracker.sqlite` for the next `git pull --rebase`.
- **Deduped on the normalised subject within a catalyst** (reuses `daily_report._norm_subject`).
  The same headline routinely arrives on several Google News feeds — the `"DRAM"` and `"NAND"`
  queries both match the same article — so the raw row count overstates reality by ~30%. Dupes are
  collapsed and rendered as `×N feeds`, keeping the loudest severity.
- **Includes alerts that *were* e-mailed instantly**, tagged `sent instantly`. Deliberate: the
  report is a complete daily record, not a "what you missed" list with unexplained gaps.
- **Skips sending on an empty window** (`--send-empty` to override) — a daily "nothing happened"
  mail is exactly the noise this change is removing.
- Pure helpers unit-tested in `tests/test_news_report.py` (loaded via importlib, same as the digest).

#### Email-volume policy (2026-08-04)

The agreed split, after per-alert mail hit **68 e-mails in 7 days — 81% of it C11 news RSS**:

| tier | catalysts | instant e-mail |
|---|---|---|
| fuses + hard data | C7, C2, C4, C1 | all severities (unchanged) |
| buy plan | `buyplan` (rung/regime flips) | all severities (unchanged) |
| numeric thermometer | C10 | HIGH and above |
| news / background | C3, C5, C6, C8, C9, C11 | **CRITICAL only** |

Everything below its floor still persists to `alerts` and the dashboard, and lands in the 09:10
roll-up. Backtested against the real 7-day history: **68 → 5 instant e-mails**, the survivors being
`buyplan CRITICAL ×1`, `c11 CRITICAL ×2`, `c1 HIGH ×1`, `c2 HIGH ×1`.

⚠️ **Tune volume via `CATALYST_EMAIL_MIN_SEVERITY`, not `CATALYST_EMAIL_DISABLE`.** In
`lib/notify._email_muted_for` the per-catalyst floor **takes precedence** over the blanket disable
list — adding `c11` to `CATALYST_EMAIL_DISABLE` while it still has a floor set is a silent no-op.

### LLM explanation path

Activated by `CATALYST_LLM_ENABLED=1`. Disabled by default in tests and dry-runs against a fresh DB unless the env var is set. The full flow (cache → CLI subprocess → JSON envelope parse → 30-day cache write) is documented in README "LLM explanation path" — when changing the prompt schema, bump `_PROMPT_VERSION` in `lib/llm.py` and re-run `scripts/llm_smoke.py`. The CLI is invoked with an explicit `--model` (`CATALYST_LLM_MODEL`, default `claude-opus-4-8`) because the default Fable 5 is region-restricted (AU) and returns `is_error`.

GitHub Actions cannot use this path (ephemeral runners can't hold the claude.ai session); the `api` backend in `lib/llm.py` is a stub for an eventual Anthropic-SDK fallback.

### Tests

`tests/` is plain pytest. `tests/fixtures/` holds canary EDGAR/RSS/XBRL snapshots — when changing regex anchors in `lib/thresholds.py` or in a catalyst module, keep the canaries green. `responses` library is used to mock HTTP. There are no integration tests against live SEC/EDGAR/yfinance.

## Source spec

Thresholds and verbatim regex anchors live in `docs/source-spec.md` (§3 and §10). Implementation plans for each catalyst and the LLM layer live in `docs/superpowers/plans/`.

## 坑 / Gotcha（踩过的，别再踩）

上面各节已详述，本节只做**索引**（SessionStart hook 靠 grep 本节标题给指针），不复述：

- **本机 clone 常年落后几千个 commit** —— 生产在另一台机器，`state:` 提交由那边的 cron 写。
  用本地 `state/tracker.sqlite` 或本地 `crontab -l` 判断「系统是否在跑」会得出相反结论。
  **先 `git fetch` 再下判断。**（2026-08-03 真踩过：据此误判「已停跑 19 天」，实际一直在跑。）
- **C4 / C5 的 transition semantics** —— 空库首扫**故意静默**，只建基线。查「为什么没告警」
  先确认有没有前一行。见「Transition semantics」节。
- **改 C1/C2 的 regex 前先读 `lib/filing_context.py`** —— 那些 pattern 匹配的是**词汇**不是
  **事件**。10-Q 的会计政策样板（"Estimates are used for, but not limited to, … impairment of
  property and equipment …"）和风险因素的虚拟语气（"… could have a material adverse effect"）
  用的是和真事件**一模一样**的词。**别用字符窗口做上下文判断** —— AMZN FY2025 10-K 里真正的
  折旧年限变更就在样板句后约 150 字符，窗口一开就把真信号一起吃掉；必须按**句子**切。
  另外扫描要用 `finditer` 不是 `search`：样板总在文件靠前，`search` 会让它挡住后面的真信号。
- **`lib/llm.py` 必须显式传 `--model`** —— CLI 默认 Fable 5 在 AU 受限，返回 `is_error`
  后静默退回静态模板。见「LLM explanation path」节。
- **改 prompt schema 必须 bump `_PROMPT_VERSION`**，会让全部缓存解释失效，这是预期的。
- **Jinja 模板必须保留 `autoescape`** —— subject/body 来自外部 RSS。见「Dashboard alert viewer」节。
- **`git log` 里的 `state: …` 是 cron 机器人写的，不是人改的，别 revert。** 见「Cron wrapper」节。
- **PJM 的 `api-subscription-key` 会轮换** —— 401/403 时从 pjm.com 的 JS bundle 刷新。
- **清 dedup 只能删 `alerts_dedup` 命名空间**，别动逐源幂等键，否则历史信号会重发。
  见「Recovering from a polluted dedup state」节。
- **调邮件量要改 `CATALYST_EMAIL_MIN_SEVERITY`，不是 `CATALYST_EMAIL_DISABLE`** ——
  `lib/notify._email_muted_for` 里**地板优先于 disable 名单**，给一个已设地板的 catalyst
  加进 disable 名单是**静默无效**的。见「Email-volume policy」节。
- **同一条新闻会从多个 Google News feed 进来**（`"DRAM"` 和 `"NAND"` 两个 query 命中同一篇），
  所以 `alerts` 表的原始行数比真实新闻条数**虚高约 30%**。统计新闻量要按 subject 去重，
  `news_report` 已经这么做了。
- **在本机跑 `pytest` 或 `--dry-run` 会修改 `state/tracker.sqlite`**（35M 二进制，已跟踪），
  导致后续 `git pull --rebase` 被未暂存改动挡住。跑完 `git checkout -- state/tracker.sqlite`。

## 局限 / Known limits

- **GitHub Actions 跑不了完整流程** —— ephemeral runner 拿不到本机 `claude` CLI 的登录会话。
  **重估条件**：`lib/llm.py` 的 `api` backend（现为 stub）接上 Anthropic SDK 之后。
- **C11 的 `UNLOCK_SCHEDULE` 是从 S-1 推算的**，earnings-linked tranche 会漂。
  **重估条件**：拿到官方确认的解禁日历。
- **没有针对 SEC / EDGAR / yfinance 的集成测试** —— `tests/fixtures/` 只有快照 canary。

## 故意没做的（不是遗漏，别"顺手补上"）

- **不改用 GitHub Actions 定时** —— 见 README「Why a single host instead of GitHub Actions」。
- **不在 catalyst 模块里改阈值** —— 数值一律进 `lib/thresholds.py`，调邮件量也改那里。
- **不给 dashboard 做服务端写入** —— Pages 是静态的，已读状态只存浏览器 localStorage，
  按设备分开是预期行为。
- **`lib/filing_context.py` 只接在 C1/C2 上，没接 C3/C6/C11** —— don't assume it exists there。
  那三个吃的是 RSS 标题（短句、没有会计样板也没有风险因素段落），是另一类误报，
  归 proximity classifier 管（见待办里 C11 那条）。
- **修 regex 误报时不回溯清洗 `alerts` 表** —— 改判据只影响之后的扫描；历史误报行还在库里，
  而 buy-plan 的保险丝读的是**近 7 天**的 `alerts`，所以一条误报最长还会再撑 7 天。
  要立刻恢复只能手删那一行，**这是需要人拍板的动作**，别自动做。

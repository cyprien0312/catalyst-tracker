# LLM Summarization Layer — Implementation Plan

**Prereq:** Foundation + C1–C5 done.

**Goal:** Replace the static `(catalyst, signal_kind)` → Explanation template registry in `lib/explanations.py` with LLM-generated explanations tailored to the specific ticker / numbers / filing snippet behind each alert. Static templates remain as the fallback path.

**Constraint:** No Anthropic API key. User has a claude.ai subscription. Primary backend is the local `claude` CLI in headless mode (`claude -p ... --output-format json`).

## Why this picks #1 + #3 from the candidate insertion points

| Candidate | Verdict | Reason |
|---|---|---|
| #1 — replace template `What/Why` in `lib/explanations.py` | **Selected** | Every alert ends here. Currently 100% static; LLM adds per-ticker/per-number specificity. Highest reader-facing ROI. |
| #2 — daily digest | Deferred | Notify path is single-message SMTP with 7-day dedup; digest framework would be a separate day of work. Lower ROI than #1 right now. |
| #3 — CRITICAL filing long-doc summary | **Selected (phase 2)** | `lib/edgar.py:get_filing_text` already fetches full filing text, but alerts only carry the URL. Adding a 200-word LLM summary for CRITICAL items costs little (≤20/month) and meaningfully reduces "open the 10-K to know if this matters" friction. |
| #4 — cross-signal synthesis | Deferred | Cross-catalyst sample is sparse (often 0 signals/day). Need #1/#3 producing data for several weeks before synthesis is meaningful. |

## Architecture

```
catalyst run → emit alert → append_context(body, catalyst, kind, ticker, snippet, numbers)
                                       │
                                       ▼ (if CATALYST_LLM_ENABLED=1)
                              lib/llm.summarize_explanation(...)
                                       │
                          ┌────────────┼────────────┐
                          ▼            ▼            ▼
                     llm_cache    claude CLI    parser
                     (sqlite)     headless      ({what, why})
                                       │
                                       ▼
                          Explanation | None  ── None ──▶ fallback to _REGISTRY
```

**Backend selector:** `CATALYST_LLM_BACKEND in {cli, api}` — `cli` is the default and works against the claude.ai subscription via `claude -p`. `api` is reserved for the future Anthropic-SDK backend; same `summarize_explanation` signature, no caller changes needed. Local-model backends (Ollama, etc.) are out of scope — the dev machine is an M2 Air and would not run them well.

## Files

- **New** `lib/llm.py` — CLI backend, prompt builder, sqlite cache, parser.
- **Edit** `lib/explanations.py` — `append_context` gains `ticker / snippet / numbers / use_llm` kwargs. Backward-compatible: existing 3-arg calls keep working.
- **New** `tests/test_llm.py` — `subprocess.run` is monkeypatched. Covers cache hits, CLI missing, timeout, non-zero exit, malformed inner JSON, code-fence tolerance, fallback paths.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `CATALYST_LLM_ENABLED` | unset (=off) | Master switch. Off by default so default deploys see no behaviour change. |
| `CATALYST_LLM_BACKEND` | `cli` | `cli` or `api`. Only `cli` implemented in MVP. |
| `CATALYST_LLM_CLAUDE_BIN` | `shutil.which("claude")` | Override binary path. Useful for cron environments where PATH is minimal. |
| `CATALYST_LLM_TIMEOUT` | `30` | Seconds. `subprocess.run` timeout. |
| `CATALYST_LLM_MODEL` | `claude-cli-default` | Cache key namespace tag; whatever model the CLI defaults to. |

## Model selection

- **Phase 1 (#1, every alert):** whichever model the user's `claude` CLI defaults to (currently Opus 4.7). Edge marginal cost is zero on the subscription; speed/quality both fine. If we later migrate to API, switch to **Haiku 4.5** — short outputs, high volume, cost-sensitive.
- **Phase 2 (#3, CRITICAL filings):** same CLI default. If migrated to API, switch to **Sonnet 4.6** — needs accounting semantics over 30k–200k tokens of filing text; volume is low (≤20/month) so unit price is affordable.

## Prompt strategy

- **System:** project tone (direct, no hedging, ≤2 short sentences per field) + JSON-only schema.
- **Few-shot:** two examples — C1 USEFUL_LIFE_SHORTENED with ticker AMZN, and C4 FCF_NEGATIVE with ticker META + numbers dict. Covers both "snippet-driven" and "number-driven" shapes.
- **User:** JSON object `{catalyst, signal_kind, ticker, numbers, snippet}` with snippet truncated to 4000 chars.
- **Output:** plain JSON `{"what": "...", "why": "..."}`. Parser tolerates surrounding ```json fences. Strings shorter than 10/20 chars are rejected → fallback.

## Cache

- Table `llm_cache(key TEXT PRIMARY KEY, value TEXT, ts INTEGER)` in `state/tracker.sqlite`, created on demand. Owned by `lib/llm.py` (does not extend `State`).
- Key = `sha256(prompt_version | model_tag | catalyst | signal_kind | ticker | sha256(snippet[:4000]) | numbers)`. Prompt version is bumped whenever the system/few-shot text changes; snippet is hashed at 4000 chars so boilerplate-heavy filings don't collide.
- TTL = 30 days. Reads past TTL are treated as miss.
- Cache failures swallow silently — never break the caller.

## Failure mode

Every external dependency in `lib/llm.py` is wrapped:

- CLI missing → `None`
- `TimeoutExpired` / `OSError` → `None`
- Non-zero exit / empty stdout → `None`
- Envelope JSON malformed → `None`
- Envelope reports error / non-success subtype → `None`
- Inner result not parseable → `None`
- `what`/`why` missing or too short → `None`
- sqlite error → `None` (no cache, but call still works)

`append_context` additionally wraps the whole call in `try/except Exception` so even unanticipated failures fall back to the static template.

## Tasks

1. **MVP step 1 — `lib/llm.py`** (CLI backend only). Implements `summarize_explanation(...)`, prompt builder, cache, parser.
2. **MVP step 2 — `append_context` kwargs.** Adds `ticker / snippet / numbers / use_llm`. Default `use_llm=True` but gated by env flag so default deploys see no change.
3. **MVP step 3 — tests.** `tests/test_llm.py`, 10 cases, no real CLI spawn.
4. **Pilot rollout — C3 only.** `catalysts/c3_openai.py` call sites pass `ticker`, `snippet=hits_text[:4000]`. Run for one week with `CATALYST_LLM_ENABLED=1`. Inspect a sample of alerts and the `llm_cache` table.
5. **Rollout to C1/C2/C4/C5.** Each call site gets the relevant context: C1 → filing snippet, C2 → 8-K item phrase, C4 → numbers dict (`capex_ocf`, `delta`), C5 → MW/strip numbers.
6. **Phase 2 — CRITICAL filing summary.** New helper `summarize_filing(catalyst, accession, filing_text) -> str | None` in `lib/llm.py`. Called in C1/C2 paths when the alert is CRITICAL. Cached by accession + first-500-chars hash.
7. **Future — API backend.** When the user has an Anthropic API key, add `_call_anthropic_api` behind `CATALYST_LLM_BACKEND=api`. No caller changes.

## Cost / quota

- **CLI backend (current):** marginal cost = $0. Bound by claude.ai subscription rate limits. With cache TTL 30 days and observed alert volume ~30/day, expected CLI invocations are <10/day → well within subscription limits. Cron should `sleep 2` between alerts as a courtesy.
- **API backend (future):** Haiku 4.5 #1 ≈ $1.50/month; Sonnet 4.6 #3 ≈ $2/month. ~$4/month total.

## Rollback

- **Disable:** unset `CATALYST_LLM_ENABLED` (or set to anything other than `1`). All `append_context` calls instantly fall back to static templates. No code change, no restart needed beyond the next cron tick.
- **Clear cache only:** `sqlite3 state/tracker.sqlite "DELETE FROM llm_cache"`. Independent of tracker state — safe to wipe any time.
- **Full uninstall:** delete `lib/llm.py`, revert `lib/explanations.py` `append_context` signature to pre-LLM (`catalyst`, `signal_kind` only), drop `tests/test_llm.py`. The `llm_cache` table can be left in place — it's harmless.

## Status

- ✅ Steps 1–3 (MVP) — landed 2026-05-14. All 102 tests pass (10 new + 92 existing, no regressions).
- ✅ Cache-key correctness fix — landed 2026-05-14. Prompt version + `sha256(snippet[:4000])` in key; fixes silent stale-cache risk when prompts change or boilerplate-heavy filings collide.
- ✅ Per-call timeout read — landed 2026-05-14. Default lowered 60s → 30s.
- ✅ Observability logging — landed 2026-05-14. Structured `llm.hit` / `llm.miss` / `llm.fallback` events.
- ✅ `scripts/llm_smoke.py` — landed 2026-05-14. CLI envelope smoke test.
- ⏳ Step 4 (C3 pilot) — pending.
- ⏳ Steps 5–7 — pending pilot results.

### Entry criteria for Step 4 (C3 pilot)

Before flipping `CATALYST_LLM_ENABLED=1` in cron:

- [ ] `python scripts/llm_smoke.py` returns exit 0.
- [ ] `catalysts/c3_openai.py` passes `snippet = (title + " " + summary)[:4000]` from the RSS hit, and `ticker=None` (OpenAI is private — no ticker).
- [ ] Cron wrapper has `sleep 2` between alerts to stay under the subscription rate limit.
- [ ] Tail logs for the first 24h and confirm at least one `llm.miss` event (proving the LLM path actually fired) plus zero unhandled exceptions.

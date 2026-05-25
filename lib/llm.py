"""LLM summarization layer for catalyst explanations.

Calls the local `claude` CLI in headless mode (`claude -p ... --output-format json`),
so it works against the user's claude.ai subscription with no API key. Results are
cached in the project sqlite DB. Any failure returns None — callers fall back to
the static template registry in lib.explanations.

Gated by env var CATALYST_LLM_ENABLED=1. Default off, so existing behaviour
(static templates) is unchanged unless explicitly turned on.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from lib.explanations import Explanation
from lib.log import get_logger
from lib.state import DEFAULT_DB

_CACHE_TTL_SECONDS = 30 * 86400
_SNIPPET_LIMIT = 4000
_PROMPT_VERSION = "v2"

_log = get_logger(__name__)


def _timeout() -> int:
    try:
        return int(os.environ.get("CATALYST_LLM_TIMEOUT", "30"))
    except ValueError:
        return 30


def _sleep_after() -> float:
    """Seconds to sleep after a successful CLI call, as a rate-limit courtesy.

    Only applies after a fresh CLI invocation — cache hits and fallback paths
    are not delayed. Set CATALYST_LLM_SLEEP_AFTER=0 to disable.
    """
    try:
        return max(0.0, float(os.environ.get("CATALYST_LLM_SLEEP_AFTER", "2")))
    except ValueError:
        return 2.0

_SYSTEM_PROMPT = (
    "You are writing a short, direct explanation for an alert in an AI-infrastructure "
    "\"bubble-stress\" tracker. The reader is bilingual (English / 中文).\n"
    "Tone: direct, no hedging, no marketing language. 1-2 short sentences per field.\n"
    "Output ONLY a single JSON object with FOUR keys:\n"
    "  - what:    1-2 sentences in English on what literally happened. Cite ticker / number / phrase if given.\n"
    "  - why:     1-3 sentences in English on why it matters for the AI-capex / bubble-stress thesis.\n"
    "  - what_zh: 与 what 等价的简体中文版本。保留专有名词 (ticker / 公司名 / 数字 / SEC / 8-K 等) 不翻译。\n"
    "  - why_zh:  与 why 等价的简体中文版本，自然中文表达，不要逐字直译，但要保留所有数字和事实。\n"
    "Do not include any prose, code fences, or commentary outside the JSON object."
)

_FEWSHOT: list[tuple[dict[str, Any], dict[str, str]]] = [
    (
        {
            "catalyst": "C1",
            "signal_kind": "USEFUL_LIFE_SHORTENED_6_TO_5",
            "ticker": "AMZN",
            "numbers": None,
            "snippet": None,
        },
        {
            "what": "AMZN told the SEC it is shortening the useful life of servers and networking equipment from six years to five.",
            "why": "Reverses the 2022-2023 tailwind that flattered hyperscaler earnings. Implies hardware is being retired faster than planned — likely because next-gen silicon outperforms current-gen by enough to make running old chips uneconomic. Bearish for the AI-capex-payback narrative.",
            "what_zh": "AMZN 向 SEC 披露，将服务器与网络设备的折旧年限从 6 年缩短到 5 年。",
            "why_zh": "这逆转了 2022-2023 年通过延长折旧美化超大规模厂商利润的会计红利。隐含意义是硬件比预期更快被淘汰——很可能因为新一代芯片的性能优势已经大到让继续使用旧卡变得不划算。对 AI capex 回本逻辑是利空信号。",
        },
    ),
    (
        {
            "catalyst": "C4",
            "signal_kind": "FCF_NEGATIVE",
            "ticker": "META",
            "numbers": {"ttm_fcf_prior_b": 4.2, "ttm_fcf_now_b": -1.1},
            "snippet": None,
        },
        {
            "what": "META's trailing-twelve-month free cash flow flipped from +$4.2B to -$1.1B.",
            "why": "Capex now exceeds all operating cash — the gap is funded by debt or balance-sheet drawdown. Crossing zero on TTM FCF is a classic late-cycle signal that the spend cycle is outrunning the revenue cycle.",
            "what_zh": "META 过去 12 个月的自由现金流从 +$4.2B 翻负至 -$1.1B。",
            "why_zh": "资本开支已经超过全部经营现金流，缺口要靠举债或动用资产负债表填。TTM 自由现金流跌破零是经典的周期晚期信号——支出节奏在跑赢收入节奏。",
        },
    ),
]


def _is_enabled() -> bool:
    return os.environ.get("CATALYST_LLM_ENABLED") == "1"


def _claude_bin() -> str | None:
    return os.environ.get("CATALYST_LLM_CLAUDE_BIN") or shutil.which("claude")


def _model_tag() -> str:
    return os.environ.get("CATALYST_LLM_MODEL", "claude-cli-default")


def _build_prompt(
    catalyst: str,
    signal_kind: str,
    ticker: str | None,
    snippet: str | None,
    numbers: dict[str, Any] | None,
) -> str:
    parts: list[str] = [_SYSTEM_PROMPT, "", "Examples:"]
    for ex_in, ex_out in _FEWSHOT:
        parts.append(f"Input: {json.dumps(ex_in, ensure_ascii=False)}")
        parts.append(f"Output: {json.dumps(ex_out, ensure_ascii=False)}")
        parts.append("")
    user_input = {
        "catalyst": catalyst,
        "signal_kind": signal_kind,
        "ticker": ticker,
        "numbers": numbers,
        "snippet": (snippet or "")[:_SNIPPET_LIMIT] or None,
    }
    parts.append(f"Input: {json.dumps(user_input, ensure_ascii=False)}")
    parts.append("Output:")
    return "\n".join(parts)


def _cache_key(
    catalyst: str,
    signal_kind: str,
    ticker: str | None,
    snippet: str | None,
    numbers: dict[str, Any] | None,
) -> str:
    snippet_digest = hashlib.sha256(
        (snippet or "")[:_SNIPPET_LIMIT].encode("utf-8")
    ).hexdigest()
    payload = json.dumps(
        {
            "v": _PROMPT_VERSION,
            "m": _model_tag(),
            "c": catalyst.upper(),
            "k": signal_kind,
            "t": ticker,
            "s": snippet_digest,
            "n": numbers,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _open_cache(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS llm_cache ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL, ts INTEGER NOT NULL)"
    )
    return conn


def _cache_get(db_path: Path, key: str) -> dict[str, str] | None:
    try:
        with _open_cache(db_path) as conn:
            row = conn.execute(
                "SELECT value, ts FROM llm_cache WHERE key=?", (key,)
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    value_json, ts = row
    if int(time.time()) - int(ts) > _CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(value_json)
    except json.JSONDecodeError:
        return None


def _cache_put(db_path: Path, key: str, value: dict[str, str]) -> None:
    try:
        with _open_cache(db_path) as conn:
            conn.execute(
                "INSERT INTO llm_cache(key, value, ts) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                (key, json.dumps(value, ensure_ascii=False), int(time.time())),
            )
    except sqlite3.Error:
        pass  # cache failures must not break the caller


def _call_claude_cli(prompt: str) -> str | None:
    """Run `claude -p ... --output-format json` and return the inner result string."""
    binary = _claude_bin()
    if binary is None:
        return None
    try:
        proc = subprocess.run(
            [binary, "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=_timeout(),
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if envelope.get("is_error") or envelope.get("subtype") != "success":
        return None
    result = envelope.get("result")
    return result if isinstance(result, str) else None


def _parse_result(raw: str) -> Explanation | None:
    """Extract the {what, why, what_zh, why_zh} JSON object from a model response.

    English fields are required (what >= 10, why >= 20 chars). Chinese fields
    are best-effort: present only if the model produced usable strings.
    """
    text = raw.strip()
    # Tolerate ```json fences or surrounding chatter.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    what = obj.get("what")
    why = obj.get("why")
    if not isinstance(what, str) or not isinstance(why, str):
        return None
    what = what.strip()
    why = why.strip()
    if len(what) < 10 or len(why) < 20:
        return None
    what_zh = obj.get("what_zh")
    why_zh = obj.get("why_zh")
    what_zh = what_zh.strip() if isinstance(what_zh, str) and what_zh.strip() else None
    why_zh = why_zh.strip() if isinstance(why_zh, str) and why_zh.strip() else None
    return Explanation(what=what, why=why, what_zh=what_zh, why_zh=why_zh)


def summarize_explanation(
    catalyst: str,
    signal_kind: str,
    *,
    ticker: str | None = None,
    snippet: str | None = None,
    numbers: dict[str, Any] | None = None,
    db_path: Path | str = DEFAULT_DB,
) -> Explanation | None:
    """Return an LLM-generated Explanation, or None on any failure.

    Returning None is the signal for callers to fall back to the static
    template registry in lib.explanations. The function never raises.
    """
    if not _is_enabled():
        _log.info(
            "llm.fallback catalyst=%s signal_kind=%s ticker=%s reason=disabled",
            catalyst, signal_kind, ticker,
        )
        return None
    db = Path(db_path)
    key = _cache_key(catalyst, signal_kind, ticker, snippet, numbers)
    cached = _cache_get(db, key)
    if cached is not None:
        what, why = cached.get("what"), cached.get("why")
        if isinstance(what, str) and isinstance(why, str):
            _log.info(
                "llm.hit catalyst=%s signal_kind=%s ticker=%s",
                catalyst, signal_kind, ticker,
            )
            return Explanation(
                what=what, why=why,
                what_zh=cached.get("what_zh") or None,
                why_zh=cached.get("why_zh") or None,
            )
        _log.info(
            "llm.fallback catalyst=%s signal_kind=%s ticker=%s reason=cache_corrupt",
            catalyst, signal_kind, ticker,
        )
        return None
    if _claude_bin() is None:
        _log.info(
            "llm.fallback catalyst=%s signal_kind=%s ticker=%s reason=cli_missing",
            catalyst, signal_kind, ticker,
        )
        return None
    prompt = _build_prompt(catalyst, signal_kind, ticker, snippet, numbers)
    raw = _call_claude_cli(prompt)
    if raw is None:
        _log.info(
            "llm.fallback catalyst=%s signal_kind=%s ticker=%s reason=cli_error",
            catalyst, signal_kind, ticker,
        )
        return None
    explanation = _parse_result(raw)
    if explanation is None:
        _log.info(
            "llm.fallback catalyst=%s signal_kind=%s ticker=%s reason=parse_failed",
            catalyst, signal_kind, ticker,
        )
        return None
    _cache_put(db, key, {
        "what": explanation.what,
        "why": explanation.why,
        "what_zh": explanation.what_zh,
        "why_zh": explanation.why_zh,
    })
    _log.info(
        "llm.miss catalyst=%s signal_kind=%s ticker=%s",
        catalyst, signal_kind, ticker,
    )
    delay = _sleep_after()
    if delay > 0:
        time.sleep(delay)
    return explanation

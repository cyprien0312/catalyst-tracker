"""Tests for the LLM summarization layer.

These never spawn a real `claude` CLI — `_call_claude_cli` is monkeypatched.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from lib import llm
from lib.explanations import Explanation, append_context


def _envelope(result_obj: dict) -> str:
    """Mimic what `claude -p --output-format json` writes to stdout."""
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": json.dumps(result_obj),
        }
    )


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "tracker.sqlite"


@pytest.fixture
def enable_llm(monkeypatch):
    monkeypatch.setenv("CATALYST_LLM_ENABLED", "1")
    monkeypatch.setenv("CATALYST_LLM_MODEL", "test-model")
    # Tests must never actually sleep; the rate-limit courtesy is verified
    # in test_sleep_after_successful_cli_call below with explicit patching.
    monkeypatch.setenv("CATALYST_LLM_SLEEP_AFTER", "0")


def test_disabled_by_default_returns_none(monkeypatch, tmp_db):
    monkeypatch.delenv("CATALYST_LLM_ENABLED", raising=False)
    assert llm.summarize_explanation("C1", "USEFUL_LIFE_STUDY", db_path=tmp_db) is None


def test_happy_path_parses_and_caches(monkeypatch, tmp_db, enable_llm):
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=_envelope({"what": "AMZN shortened useful life to five years.",
                              "why": "Reverses prior earnings tailwind and signals faster hardware churn."}),
            stderr="",
        )

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm, "_claude_bin", lambda: "/usr/bin/fake-claude")

    out = llm.summarize_explanation(
        "C1", "USEFUL_LIFE_SHORTENED_6_TO_5",
        ticker="AMZN", db_path=tmp_db,
    )
    assert isinstance(out, Explanation)
    assert "AMZN" in out.what
    assert calls["n"] == 1

    # Second call must hit the cache, not the CLI.
    out2 = llm.summarize_explanation(
        "C1", "USEFUL_LIFE_SHORTENED_6_TO_5",
        ticker="AMZN", db_path=tmp_db,
    )
    assert out2 == out
    assert calls["n"] == 1


def test_cli_missing_returns_none(monkeypatch, tmp_db, enable_llm):
    monkeypatch.setattr(llm, "_claude_bin", lambda: None)
    assert llm.summarize_explanation("C3", "CRITICAL", db_path=tmp_db) is None


def test_timeout_returns_none(monkeypatch, tmp_db, enable_llm):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm, "_claude_bin", lambda: "/usr/bin/fake-claude")
    assert llm.summarize_explanation("C3", "CRITICAL", db_path=tmp_db) is None


def test_nonzero_exit_returns_none(monkeypatch, tmp_db, enable_llm):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm, "_claude_bin", lambda: "/usr/bin/fake-claude")
    assert llm.summarize_explanation("C3", "CRITICAL", db_path=tmp_db) is None


def test_malformed_inner_json_returns_none(monkeypatch, tmp_db, enable_llm):
    def fake_run(cmd, **kwargs):
        env = json.dumps({
            "type": "result", "subtype": "success", "is_error": False,
            "result": "not even close to JSON",
        })
        return subprocess.CompletedProcess(cmd, 0, stdout=env, stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm, "_claude_bin", lambda: "/usr/bin/fake-claude")
    assert llm.summarize_explanation("C3", "CRITICAL", db_path=tmp_db) is None


def test_parse_tolerates_code_fence(monkeypatch, tmp_db, enable_llm):
    fenced = (
        "```json\n"
        "{\"what\": \"OpenAI hit a CRITICAL keyword in MSFT 10-K.\","
        " \"why\": \"Linchpin AI customer for MSFT and NVDA — any distress cascades.\"}\n"
        "```"
    )

    def fake_run(cmd, **kwargs):
        env = json.dumps({
            "type": "result", "subtype": "success", "is_error": False,
            "result": fenced,
        })
        return subprocess.CompletedProcess(cmd, 0, stdout=env, stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm, "_claude_bin", lambda: "/usr/bin/fake-claude")
    out = llm.summarize_explanation("C3", "CRITICAL", db_path=tmp_db)
    assert isinstance(out, Explanation)
    assert "OpenAI" in out.what


def test_cache_key_distinguishes_long_snippets_with_same_prefix(enable_llm):
    prefix = "A" * 600
    snip_a = prefix + "TAIL_A"
    snip_b = prefix + "TAIL_B"
    key_a = llm._cache_key("C1", "USEFUL_LIFE_STUDY", "AMZN", snip_a, None)
    key_b = llm._cache_key("C1", "USEFUL_LIFE_STUDY", "AMZN", snip_b, None)
    assert key_a != key_b


def test_cache_key_changes_when_prompt_version_bumped(monkeypatch, enable_llm):
    snip = "some filing language here"
    monkeypatch.setattr(llm, "_PROMPT_VERSION", "v1")
    key_v1 = llm._cache_key("C1", "USEFUL_LIFE_STUDY", "AMZN", snip, None)
    monkeypatch.setattr(llm, "_PROMPT_VERSION", "v2")
    key_v2 = llm._cache_key("C1", "USEFUL_LIFE_STUDY", "AMZN", snip, None)
    assert key_v1 != key_v2


def test_timeout_env_var_read_per_call(monkeypatch, tmp_db, enable_llm):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, stdout=_envelope({
            "what": "AMZN shortened useful life to five years.",
            "why": "Reverses prior earnings tailwind and signals faster hardware churn.",
        }), stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm, "_claude_bin", lambda: "/usr/bin/fake-claude")
    monkeypatch.setenv("CATALYST_LLM_TIMEOUT", "7")
    llm.summarize_explanation(
        "C1", "USEFUL_LIFE_SHORTENED_6_TO_5", ticker="AMZN", db_path=tmp_db,
    )
    assert seen["timeout"] == 7


def test_timeout_default_is_thirty(monkeypatch):
    monkeypatch.delenv("CATALYST_LLM_TIMEOUT", raising=False)
    assert llm._timeout() == 30


def test_append_context_falls_back_when_llm_disabled(monkeypatch):
    monkeypatch.delenv("CATALYST_LLM_ENABLED", raising=False)
    out = append_context("body\n", "C4", "FCF_NEGATIVE", ticker="META")
    assert "free cash flow" in out.lower()
    assert "What this means:" in out


def test_append_context_uses_llm_when_enabled(monkeypatch, tmp_path, enable_llm):
    monkeypatch.setattr(
        "lib.llm.DEFAULT_DB", tmp_path / "tracker.sqlite", raising=False
    )

    def fake_summarize(catalyst, signal_kind, *, ticker=None, snippet=None,
                       numbers=None, db_path=None):
        return Explanation(
            what=f"LLM said {ticker} hit {signal_kind}.",
            why="LLM-rendered implication that satisfies the length floor for tests.",
        )

    monkeypatch.setattr("lib.llm.summarize_explanation", fake_summarize)

    out = append_context("body\n", "C4", "FCF_NEGATIVE", ticker="META")
    assert "LLM said META hit FCF_NEGATIVE" in out


def test_append_context_falls_back_when_llm_returns_none(monkeypatch, enable_llm):
    monkeypatch.setattr(
        "lib.llm.summarize_explanation",
        lambda *a, **kw: None,
    )
    out = append_context("body\n", "C1", "USEFUL_LIFE_SHORTENED_6_TO_5", ticker="AMZN")
    # Falls back to the static template that mentions hyperscalers.
    assert "hyperscaler" in out.lower()


def test_append_context_falls_back_when_llm_raises(monkeypatch, enable_llm):
    def boom(*a, **kw):
        raise RuntimeError("network died")

    monkeypatch.setattr("lib.llm.summarize_explanation", boom)
    out = append_context("body\n", "C1", "USEFUL_LIFE_SHORTENED_6_TO_5")
    assert "What this means:" in out
    assert "hyperscaler" in out.lower()


def test_sleep_after_successful_cli_call(monkeypatch, tmp_db, enable_llm):
    """Successful CLI call sleeps; cache hit and fallback do not."""
    monkeypatch.setenv("CATALYST_LLM_SLEEP_AFTER", "1.5")
    slept: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0,
            stdout=_envelope({"what": "OpenAI hit a CRITICAL keyword in MSFT filing.",
                              "why": "Linchpin AI customer — any distress cascades through the stack."}),
            stderr="",
        )

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm, "_claude_bin", lambda: "/usr/bin/fake-claude")

    # First call -> CLI hit -> should sleep once.
    out = llm.summarize_explanation("C3", "CRITICAL", ticker="MSFT", db_path=tmp_db)
    assert isinstance(out, Explanation)
    assert slept == [1.5]

    # Second call -> cache hit -> must NOT sleep again.
    out2 = llm.summarize_explanation("C3", "CRITICAL", ticker="MSFT", db_path=tmp_db)
    assert out2 == out
    assert slept == [1.5]


def test_sleep_disabled_when_env_zero(monkeypatch, tmp_db, enable_llm):
    """CATALYST_LLM_SLEEP_AFTER=0 (the test default) skips the sleep entirely."""
    slept: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0,
            stdout=_envelope({"what": "ok ok ok ok ok",
                              "why": "this is a perfectly adequate reason string."}),
            stderr="",
        )

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm, "_claude_bin", lambda: "/usr/bin/fake-claude")
    llm.summarize_explanation("C3", "CRITICAL", db_path=tmp_db)
    assert slept == []

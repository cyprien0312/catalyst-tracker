#!/usr/bin/env python3
"""End-to-end smoke probe for the `claude` CLI backend used by lib.llm.

Run this manually before flipping CATALYST_LLM_ENABLED=1 in production. It makes
a real call against the user's claude.ai subscription, so it costs real quota.

Usage:
    python scripts/llm_smoke.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Force-enable the LLM path before importing lib.llm so the user doesn't have
# to remember to export the env var.
os.environ["CATALYST_LLM_ENABLED"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.explanations import Explanation  # noqa: E402
from lib.llm import summarize_explanation  # noqa: E402


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _resolve_binary() -> str:
    binary = os.environ.get("CATALYST_LLM_CLAUDE_BIN") or shutil.which("claude")
    if not binary:
        _fail(
            "no `claude` binary found on PATH and CATALYST_LLM_CLAUDE_BIN is unset. "
            "Install the Claude CLI or set CATALYST_LLM_CLAUDE_BIN to its absolute path."
        )
    print(f"using claude binary: {binary}")
    return binary  # type: ignore[return-value]


def _envelope_check(binary: str) -> None:
    """Directly invoke the CLI with a trivial prompt and validate envelope shape."""
    prompt = (
        'Reply with the JSON object {"what":"ok ok ok",'
        '"why":"this is just a smoke test of the envelope shape"} and nothing else.'
    )
    try:
        proc = subprocess.run(
            [binary, "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _fail(f"claude CLI invocation failed: {exc!r}")
        return  # unreachable
    if proc.returncode != 0:
        _fail(
            f"claude CLI exited with code {proc.returncode}.\n"
            f"stderr (500 chars): {proc.stderr[:500]!r}"
        )
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        _fail(
            f"claude CLI stdout was not valid JSON: {exc}.\n"
            f"raw stdout (500 chars): {proc.stdout[:500]!r}"
        )
        return  # unreachable
    expected_keys = {"is_error", "subtype", "result"}
    missing = expected_keys - set(envelope.keys())
    if missing:
        _fail(
            f"envelope missing expected keys: {sorted(missing)}.\n"
            f"raw stdout (500 chars): {proc.stdout[:500]!r}"
        )
    if envelope.get("is_error"):
        _fail(f"envelope reports is_error=True: {proc.stdout[:500]!r}")
    if envelope.get("subtype") != "success":
        _fail(f"envelope subtype is not 'success': {envelope.get('subtype')!r}")
    if not isinstance(envelope.get("result"), str):
        _fail(f"envelope.result is not a string: {type(envelope.get('result')).__name__}")
    print("envelope check passed (is_error/subtype/result all present)")


def _end_to_end_check() -> Explanation:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "smoke_tracker.sqlite"
        result = summarize_explanation(
            "C4",
            "FCF_NEGATIVE",
            ticker="META",
            snippet=None,
            numbers={"ttm_fcf_prior_b": 4.2, "ttm_fcf_now_b": -1.1},
            db_path=db_path,
        )
    if result is None:
        _fail(
            "summarize_explanation returned None. The CLI call, JSON parse, or "
            "min-length validation in _parse_result failed. Re-run with logging "
            "enabled to see which step bailed."
        )
    if not isinstance(result, Explanation):
        _fail(f"expected Explanation instance, got {type(result).__name__}")
    # Mirror the min lengths used in _parse_result.
    if not isinstance(result.what, str) or len(result.what.strip()) < 10:
        _fail(f"`what` too short or not a string: {result.what!r}")
    if not isinstance(result.why, str) or len(result.why.strip()) < 20:
        _fail(f"`why` too short or not a string: {result.why!r}")
    return result  # type: ignore[return-value]


def main() -> int:
    binary = _resolve_binary()
    _envelope_check(binary)
    explanation = _end_to_end_check()
    snippet = explanation.what[:60].replace("\n", " ")
    print(f'OK: llm smoke passed (binary={binary}, what="{snippet}...")')
    return 0


if __name__ == "__main__":
    sys.exit(main())

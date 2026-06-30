"""Tests for the Obsidian knowledge-base bridge (lib/knowledge.py)."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import knowledge
from lib.knowledge import FactClaim


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    (tmp_path / "ai-infra").mkdir()
    return tmp_path


# --------------------------------------------------------------------------- #
# read / parse
# --------------------------------------------------------------------------- #
def test_load_missing_dir_returns_empty(tmp_path: Path):
    assert knowledge.load_facts(base_dir=tmp_path / "nope") == []


def test_load_skips_readme_and_topicless(base_dir: Path):
    dom = base_dir / "ai-infra"
    (dom / "README.md").write_text("# index\n", encoding="utf-8")
    (dom / "no-topic.md").write_text("---\npillar: ai-infra\n---\nbody\n", encoding="utf-8")
    (dom / "good.md").write_text(
        "---\ntopic: A real fact\npillar: ai-infra\nsources:\n  - https://x/y\n---\n"
        "## 核心事实\n- A real fact [src: https://x/y]\n",
        encoding="utf-8",
    )
    facts = knowledge.load_facts(base_dir=base_dir)
    assert [f.slug for f in facts] == ["good"]
    assert facts[0].topic == "A real fact"
    assert facts[0].sources == ("https://x/y",)


def test_manual_detection(base_dir: Path):
    dom = base_dir / "ai-infra"
    (dom / "auto.md").write_text(
        "---\ntopic: auto\ngenerated: verify-auto\nsources:\n  - https://a\n---\n", encoding="utf-8"
    )
    (dom / "manual-flag.md").write_text(
        "---\ntopic: m1\nmanual: true\ngenerated: verify-auto\nsources:\n  - https://b\n---\n",
        encoding="utf-8",
    )
    (dom / "no-marker.md").write_text(
        "---\ntopic: m2\nsources:\n  - https://c\n---\n", encoding="utf-8"
    )
    by_slug = {f.slug: f for f in knowledge.load_facts(base_dir=base_dir)}
    assert by_slug["auto"].is_manual is False
    assert by_slug["manual-flag"].is_manual is True   # explicit flag
    assert by_slug["no-marker"].is_manual is True      # no generated marker


# --------------------------------------------------------------------------- #
# relevance / render
# --------------------------------------------------------------------------- #
def _fact(slug, topic, tags=(), body="", sources=("https://s",)):
    return knowledge.Fact(slug=slug, path=Path(slug), topic=topic, tags=tuple(tags),
                          body=body, sources=tuple(sources))


def test_relevant_facts_by_catalyst_tag():
    facts = [_fact("c7", "credit", tags=("ai-infra", "c7")),
             _fact("c9", "btc", tags=("ai-infra", "c9"))]
    out = knowledge.relevant_facts(facts, catalyst="C7")
    assert [f.slug for f in out] == ["c7"]


def test_relevant_facts_no_filter_returns_all():
    facts = [_fact("a", "x"), _fact("b", "y")]
    assert knowledge.relevant_facts(facts) == facts


def test_render_block_and_limit():
    facts = [_fact("a", "Fact A", sources=("https://a",)),
             _fact("b", "Fact B", sources=("https://b",))]
    block = knowledge.render_facts_block(facts, limit=1)
    assert "Fact A [src: https://a]" in block
    assert "Fact B" not in block          # limit respected
    assert knowledge.render_facts_block([]) == ""


def test_facts_for_prompt_roundtrip(base_dir: Path):
    knowledge.write_fact(
        slug="c7-credit", topic="C7 credit trigger",
        claims=[FactClaim("C7 credit trigger", "https://spec#c7", "HY +75bp")],
        tags=["ai-infra", "c7"], base_dir=base_dir,
    )
    block = knowledge.facts_for_prompt(catalyst="C7", base_dir=base_dir)
    assert "C7 credit trigger" in block and "https://spec#c7" in block
    # unrelated catalyst -> no facts injected
    assert knowledge.facts_for_prompt(catalyst="C1", base_dir=base_dir) == ""


# --------------------------------------------------------------------------- #
# write (verify stage)
# --------------------------------------------------------------------------- #
def test_write_then_reread(base_dir: Path):
    path = knowledge.write_fact(
        slug="My Fact!", topic="Some claim", pillar="ai-infra",
        claims=[FactClaim("Some claim", "https://src/1", "exact quote")],
        tags=["ai-infra", "c4"], last_verified="2026-06-30", base_dir=base_dir,
    )
    assert path is not None and path.name == "my-fact.md"   # slugified
    fact = knowledge._parse_file(path)
    assert fact.topic == "Some claim"
    assert fact.sources == ("https://src/1",)
    assert fact.generated == "verify-auto"
    assert fact.last_verified == "2026-06-30"
    assert "> exact quote" in path.read_text(encoding="utf-8")


def test_write_idempotent_overwrites_same_source(base_dir: Path):
    knowledge.write_fact(slug="v1", topic="old topic",
                         claims=[FactClaim("old", "https://same", "q")], base_dir=base_dir)
    # Re-publish the same source under a different slug -> updates in place, no dup.
    knowledge.write_fact(slug="v2", topic="new topic",
                         claims=[FactClaim("new", "https://same", "q2")], base_dir=base_dir)
    facts = knowledge.load_facts(base_dir=base_dir)
    assert len(facts) == 1
    assert facts[0].topic == "new topic"


def test_write_respects_manual(base_dir: Path):
    dom = base_dir / "ai-infra"
    human = dom / "human.md"
    human.write_text(
        "---\ntopic: human owned\nmanual: true\nsources:\n  - https://shared\n---\n"
        "## 核心事实\n- human owned [src: https://shared]\n",
        encoding="utf-8",
    )
    before = human.read_text(encoding="utf-8")
    result = knowledge.write_fact(
        slug="auto", topic="auto wants this source",
        claims=[FactClaim("auto", "https://shared", "q")], base_dir=base_dir,
    )
    assert result is None                              # skipped
    assert human.read_text(encoding="utf-8") == before  # untouched
    assert len(knowledge.load_facts(base_dir=base_dir)) == 1


def test_write_distinct_sources_make_distinct_files(base_dir: Path):
    knowledge.write_fact(slug="c7", topic="t7",
                         claims=[FactClaim("t7", "https://spec#c7", "q7")], base_dir=base_dir)
    knowledge.write_fact(slug="c8", topic="t8",
                         claims=[FactClaim("t8", "https://spec#c8", "q8")], base_dir=base_dir)
    assert len(knowledge.load_facts(base_dir=base_dir)) == 2


def test_frontmatter_quotes_risky_scalars(base_dir: Path):
    # A topic with a colon must round-trip (emitted JSON-quoted, parsed back clean).
    path = knowledge.write_fact(
        slug="colon", topic="C4: capex crosses 110%",
        claims=[FactClaim("C4: capex crosses 110%", "https://s", None)], base_dir=base_dir,
    )
    assert knowledge._parse_file(path).topic == "C4: capex crosses 110%"

"""Bridge to the unified Obsidian knowledge base (read + verify-stage write).

The vault holds ONE fact-checked corpus shared across every project, at
``<CATALYST_KNOWLEDGE_DIR>/<domain>/`` — one fact per markdown file with YAML
front-matter (``topic`` / ``pillar`` / ``last_verified`` / ``sources`` /
``status`` / ...). See ``<vault>/knowledge/README.md`` for the convention.

catalyst-tracker connects to it the same way other projects do:

* **READ** — :func:`facts_for_prompt` pulls relevant ``ai-infra`` facts and renders
  a compact block injected into the LLM explanation + daily-digest prompts.
* **WRITE (verify stage)** — :func:`write_fact` persists a confirmed fact back as a
  properly-formatted ``generated: verify-auto`` entry. ``scripts/sync_knowledge.py``
  drives this to publish the tracker's threshold facts into the ``ai-infra`` domain.

Design contract (mirrors :mod:`lib.llm`): **never raise into callers**. A missing
directory or a parse error makes reads return ``[]`` and writes a logged no-op.
Hand-curated files (front-matter ``manual: true``, or simply lacking a
``generated:`` marker) are NEVER overwritten — the human always wins.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from lib.log import get_logger

_log = get_logger(__name__)

_DEFAULT_DIR = Path.home() / "ObsidianVault" / "knowledge"
_DEFAULT_DOMAIN = "ai-infra"

# A YAML plain scalar is safe only when it has no leading indicator char and no
# ``:``/``#`` that would change the parse. Anything else we emit JSON-quoted
# (valid YAML, round-trips through yaml.safe_load, keeps 中文 readable).
_PLAIN_SAFE = re.compile(r"^[^\s!&*?{}\[\],#|>@`\"'%:-][^:#\n]*$")


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def knowledge_dir() -> Path:
    """Root of the shared corpus. Override with ``CATALYST_KNOWLEDGE_DIR``."""
    return Path(os.environ.get("CATALYST_KNOWLEDGE_DIR", str(_DEFAULT_DIR))).expanduser()


def domain() -> str:
    """Domain folder this project reads/writes. Override ``CATALYST_KNOWLEDGE_DOMAIN``."""
    return os.environ.get("CATALYST_KNOWLEDGE_DOMAIN", _DEFAULT_DOMAIN)


def _today() -> str:
    return _dt.date.today().isoformat()


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FactClaim:
    """A single sourced claim inside a knowledge note."""
    claim: str
    src: str
    quote: str | None = None


@dataclass(frozen=True)
class Fact:
    """A parsed knowledge note (one ``.md`` file)."""
    slug: str
    path: Path
    topic: str
    pillar: str | None = None
    last_verified: str | None = None
    sources: tuple[str, ...] = ()
    status: str | None = None
    generated: str | None = None
    manual: bool = False
    tags: tuple[str, ...] = ()
    body: str = ""
    frontmatter: dict = field(default_factory=dict)

    @property
    def is_manual(self) -> bool:
        """True if a write must NOT clobber this file (human-curated)."""
        # Per the corpus README: ``manual: true`` OR the absence of a
        # ``generated`` marker both mean hand-curated.
        return bool(self.manual) or self.generated is None


# --------------------------------------------------------------------------- #
# front-matter parse / emit
# --------------------------------------------------------------------------- #
def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return ``(frontmatter_dict, body)``. Tolerates a missing block."""
    if not text.startswith("---"):
        return {}, text
    # First line is ``---``; find the closing ``---`` fence.
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    raw = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, body


def _as_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


def _parse_file(path: Path) -> Fact | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = _split_frontmatter(text)
    topic = str(meta.get("topic") or "").strip()
    if not topic:
        # A note with no topic is not usable as a fact; skip quietly.
        return None
    return Fact(
        slug=path.stem,
        path=path,
        topic=topic,
        pillar=(str(meta["pillar"]).strip() if meta.get("pillar") else None),
        last_verified=(str(meta["last_verified"]) if meta.get("last_verified") else None),
        sources=_as_tuple(meta.get("sources")),
        status=(str(meta["status"]).strip() if meta.get("status") else None),
        generated=(str(meta["generated"]).strip() if meta.get("generated") else None),
        manual=bool(meta.get("manual")),
        tags=_as_tuple(meta.get("tags")),
        body=body.strip(),
        frontmatter=meta,
    )


def _scalar(value) -> str:
    """Render a front-matter scalar: plain when safe, else JSON-quoted (valid YAML)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        v = value.strip()
        if v and _PLAIN_SAFE.match(v) and ": " not in v and not v.endswith(":"):
            return v
        return json.dumps(v, ensure_ascii=False)
    return str(value)


def _dump_frontmatter(pairs: list[tuple[str, object]]) -> str:
    """Emit front-matter in a fixed, human-friendly key order matching house style."""
    out: list[str] = ["---"]
    for key, value in pairs:
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            if not value:
                continue
            out.append(f"{key}:")
            out.extend(f"  - {_scalar(v)}" for v in value)
        else:
            out.append(f"{key}: {_scalar(value)}")
    out.append("---")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #
def load_facts(*, dom: str | None = None, base_dir: Path | None = None) -> list[Fact]:
    """Load every fact note in ``<base_dir>/<dom>/``. Returns ``[]`` on any failure."""
    root = (base_dir or knowledge_dir()) / (dom or domain())
    try:
        if not root.is_dir():
            return []
        paths = sorted(p for p in root.glob("*.md") if p.name.lower() != "readme.md")
    except OSError:
        return []
    facts: list[Fact] = []
    for path in paths:
        fact = _parse_file(path)
        if fact is not None:
            facts.append(fact)
    return facts


def _haystack(fact: Fact) -> str:
    return " ".join((fact.topic, fact.body, " ".join(fact.tags))).lower()


def relevant_facts(
    facts: list[Fact],
    *,
    catalyst: str | None = None,
    ticker: str | None = None,
    keywords: list[str] | None = None,
) -> list[Fact]:
    """Filter facts by catalyst tag / ticker / free keywords.

    With no filter at all, returns ``facts`` unchanged (cross-signal context, used
    by the daily digest). With a catalyst/ticker/keywords filter, returns only the
    facts that match — so a per-alert prompt never gets dumped unrelated facts.
    """
    if not (catalyst or ticker or keywords):
        return facts
    cat = catalyst.lower() if catalyst else None
    # Free-text needles match as substrings of the note; the catalyst code matches
    # ONLY as an exact tag (so "c1" never bleeds into "c10").
    substrings: list[str] = []
    if ticker:
        substrings.append(ticker.lower())
    if keywords:
        substrings.extend(k.lower() for k in keywords if k)
    out: list[Fact] = []
    for fact in facts:
        tags = {t.lower() for t in fact.tags}
        if cat and cat in tags:
            out.append(fact)
            continue
        if substrings:
            hay = _haystack(fact)
            if any(s in hay for s in substrings):
                out.append(fact)
    return out


def render_facts_block(facts: list[Fact], *, limit: int = 8) -> str:
    """Render facts as a compact, prompt-injectable block (empty string if none)."""
    if not facts:
        return ""
    lines = ["Verified facts from the shared knowledge base "
             "(use only if relevant; cite the source URL if you rely on one):"]
    for fact in facts[:limit]:
        src = f" [src: {fact.sources[0]}]" if fact.sources else ""
        lines.append(f"- {fact.topic}{src}")
    return "\n".join(lines)


def facts_for_prompt(
    *,
    catalyst: str | None = None,
    ticker: str | None = None,
    keywords: list[str] | None = None,
    limit: int = 8,
    dom: str | None = None,
    base_dir: Path | None = None,
) -> str:
    """One-call read path for prompt injection. Never raises; returns ``""`` on failure."""
    try:
        facts = load_facts(dom=dom, base_dir=base_dir)
        chosen = relevant_facts(facts, catalyst=catalyst, ticker=ticker, keywords=keywords)
        return render_facts_block(chosen, limit=limit)
    except Exception:  # defensive: a read must never break alerting
        _log.exception("knowledge.read_failed catalyst=%s ticker=%s", catalyst, ticker)
        return ""


# --------------------------------------------------------------------------- #
# write (verify stage)
# --------------------------------------------------------------------------- #
def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "fact"


def _compose(
    *,
    topic: str,
    pillar: str | None,
    last_verified: str,
    generated: str | None,
    sources: list[str],
    status: str,
    tags: list[str],
    claims: list[FactClaim],
) -> str:
    fm = _dump_frontmatter([
        ("topic", topic),
        ("pillar", pillar),
        ("last_verified", last_verified),
        ("generated", generated),
        ("sources", sources),
        ("status", status),
        ("tags", tags),
    ])
    body = ["", "## 核心事实"]
    for c in claims:
        body.append(f"- {c.claim} [src: {c.src}]")
        if c.quote:
            body.append(f"> {c.quote}")
    return fm + "\n" + "\n".join(body).rstrip() + "\n"


def write_fact(
    *,
    slug: str,
    topic: str,
    claims: list[FactClaim],
    pillar: str | None = None,
    sources: list[str] | None = None,
    tags: list[str] | None = None,
    status: str = "verified",
    last_verified: str | None = None,
    generated: str | None = "verify-auto",
    dom: str | None = None,
    base_dir: Path | None = None,
) -> Path | None:
    """Write/refresh an auto fact note. Returns the path written, or ``None`` if skipped.

    Idempotent: an existing ``generated`` note covering the same primary source is
    overwritten in place (even if its slug differs). A human-curated note that
    shares any source — or owns the target slug — is left untouched and we skip.
    """
    if not claims:
        _log.info("knowledge.write_skip slug=%s reason=no_claims", slug)
        return None
    slug = _slugify(slug)
    pillar = pillar or (dom or domain())
    last_verified = last_verified or _today()
    if sources is None:
        seen: list[str] = []
        for c in claims:
            if c.src and c.src not in seen:
                seen.append(c.src)
        sources = seen
    tags = tags or []
    primary = sources[0] if sources else None

    root = (base_dir or knowledge_dir()) / (dom or domain())
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        _log.exception("knowledge.write_failed slug=%s reason=mkdir", slug)
        return None

    existing = load_facts(dom=dom, base_dir=base_dir)
    src_set = set(sources)
    target: Path | None = None
    for fact in existing:
        shares_source = bool(primary and primary in fact.sources) or bool(src_set & set(fact.sources))
        if fact.is_manual and (shares_source or fact.slug == slug):
            _log.info(
                "knowledge.write_skip slug=%s reason=manual_owns path=%s",
                slug, fact.path.name,
            )
            return None
        if not fact.is_manual and shares_source and target is None:
            target = fact.path  # overwrite the stale auto note in place

    if target is None:
        target = root / f"{slug}.md"

    content = _compose(
        topic=topic,
        pillar=pillar,
        last_verified=last_verified,
        generated=generated,
        sources=sources,
        status=status,
        tags=tags,
        claims=claims,
    )
    try:
        tmp = target.with_suffix(".md.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)
    except OSError:
        _log.exception("knowledge.write_failed slug=%s reason=write path=%s", slug, target)
        return None
    _log.info("knowledge.write_ok slug=%s path=%s sources=%d", slug, target.name, len(sources))
    return target

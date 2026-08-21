"""Deterministic repair of shortened citation paths (CCE-141).

`page-author` sometimes emits a citation as a bare relative path — the
committed page cited
`.claude/skills/connector-builder/references/checklist.md` at three sites and
the rewrite shortened it to `references/checklist.md`. `citation_exists`
correctly finds nothing at the repo root and blocks the page; post-CCE-140 the
deferral skip then abandons the PR, so the page is silently never written.

This module repairs the observable defect regardless of what causes it. The
safety claim is set-invariance, NOT correctness: repair never introduces a
reference to a file the pipeline had not already accepted a reference to. The
set of files the finished page points at is invariant under repair; only the
spelling of an existing pointer changes.

Uniqueness alone does not deliver that. A unique suffix match establishes only
that the candidate exists — never that the cited token was a shortening of it —
and "does not resolve" is exactly the confabulation population citation_exists
exists to block. Corroboration is therefore the ENTRY CONDITION: the candidate
must already be vouched for by a source the authoring agent did not write.
Ambiguity, zero-match and uncorroborated all leave the page untouched and
blocking.

Spec: docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_LINT_DIR = str(Path(__file__).resolve().parent / "lint")
if _LINT_DIR not in sys.path:
    sys.path.append(_LINT_DIR)

# Imported, never reimplemented: citation_exists declares these a shared-helper
# contract. Repair must agree with check_path on what a citation IS and what
# resolves, or the two drift and repair starts "fixing" tokens the linter
# deliberately skips.
from citation_exists import (  # noqa: E402
    _INLINE_CODE_RE,
    _SUFFIX_RE,
    _build_dir,
    _docs_dir,
    _is_gitignored,
    _relativize,
    _resolves,
    example_prefixes,
    exempt_tokens,
    extract_citations,
    source_roots,
    tracked_files,
)

__all__ = [
    "suffix_candidates",
    "rewrite_token",
    "repair_text",
    "tracked_files",
    "build_corroborators",
]


_GLOB_CHARS = ("*", "?", "[", "{")


def build_corroborators(
    prior_text: str | None, source_paths: set[str], files: set[str]
) -> set[str]:
    """Tracked paths corroborated by a source the authoring agent did not write.

    Rung 1 (edits, git-authoritative): a RAW substring scan of the prior
    committed page. Deliberately not extract_citations — that reads only
    backticked spans in unfenced prose and on this repo's 108-page corpus sees
    69.9% of path tokens, missing frontmatter-only and link-target-only ones.
    A raw scan does not violate the imported-never-reimplemented contract: it
    is not deciding what a citation IS, only whether a known-tracked path was
    already present.

    Rung 2 (every authoring, orchestrator-authoritative): the batch's source
    set. On a create _enforce_agent_frontmatter writes this into the page's own
    source_files, OVERWRITING the agent — so every action has a corroborator
    the agent did not author. Glob entries are excluded: expanding them would
    make the gate ceremony.

    evidence.files_read is deliberately NOT a source — an author that
    confabulates a citation can equally confabulate a files_read entry.
    """
    out = {
        p for p in source_paths if p in files and not any(c in p for c in _GLOB_CHARS)
    }
    if prior_text:
        out |= {f for f in files if f in prior_text}
    return out


def suffix_candidates(cited: str, files: set[str]) -> list[str]:
    """Tracked paths of which `cited` is a strict segment-boundary suffix.

    Segment boundaries are required, not substring matching:
    `references/checklist.md` matches
    `.claude/skills/connector-builder/references/checklist.md`, but
    `erences/checklist.md` matches nothing.

    `len(parts) > n` is what makes the shortening STRICT — it excludes the
    exact-match case, which is never a repair candidate because such a token
    already resolved.
    """
    segments = cited.split("/")
    n = len(segments)
    out = []
    for f in files:
        parts = f.split("/")
        if len(parts) > n and parts[-n:] == segments:
            out.append(f)
    return sorted(out)


def _closed_fence_lines(text: str) -> set[int]:
    """Line indices inside a CLOSED fence — the lines strip_fenced_blocks cuts.

    Mirrors that function's bookkeeping on purpose, including the awkward
    part: an UNTERMINATED fence strips nothing there, so its lines stay
    visible to extract_citations and must stay rewritable here. Any divergence
    would let repair_text report a repair that rewrite_token never applied.

    Indices are over text.split("\n") — the same split rewrite_token uses —
    so the two always align. _INLINE_CODE_RE excludes newlines, so no code
    span can straddle a line and per-line rewriting is equivalent.
    """
    fenced: set[int] = set()
    in_fence = False
    fence = ""
    start = 0
    for i, line in enumerate(text.split("\n")):
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence, start = True, stripped[:3], i
            continue
        if in_fence and stripped.startswith(fence):
            in_fence = False
            fenced.update(range(start, i + 1))
    return fenced


def rewrite_token(text: str, old: str, new: str) -> str:
    """Replace bare path `old` with `new` inside matching inline code spans.

    Matching is on the token's BARE path (suffix stripped), but the replacement
    happens inside the original token, so `path.py:Class.method` keeps its
    symbol. Every other byte of the document is preserved — this must never
    reflow or normalise the author's prose.
    """

    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        if _SUFFIX_RE.sub("", token.strip()) != old:
            return match.group(0)
        return "`" + token.replace(old, new, 1) + "`"

    fenced = _closed_fence_lines(text)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if i not in fenced:
            lines[i] = _INLINE_CODE_RE.sub(_sub, line)
    return "\n".join(lines)


def repair_text(
    text: str,
    repo_root: Path,
    config: dict,
    files: set[str],
    corroborators: set[str],
) -> tuple[str, list[tuple[str, str]], list[tuple[str, str, str]]]:
    """Repair shortened citations. Returns (new_text, repairs, declines).

    Corroboration is the ENTRY CONDITION, not an ambiguity tiebreak. A unique
    suffix match establishes only that the candidate exists — never that the
    cited token was a shortening of it, and the sole entry condition ("does
    not resolve") is exactly the confabulation population citation_exists
    exists to block. See the spec's "Why uniqueness is necessary but NOT
    sufficient".

    The invariant this delivers: repair never introduces a reference to a file
    the pipeline had not already accepted a reference to. The set of files the
    finished page points at is invariant under repair; only the spelling of an
    existing pointer changes.

    The skip order mirrors `citation_exists.check_path` deliberately. Every
    class it declines to check is a class repair must decline to touch: an
    exempt token, a reserved `example/` path, and a gitignored path are all
    unresolvable BY DESIGN, and "fixing" one would convert a deliberate
    illustration into a false claim about real code.
    """
    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    prefixes = example_prefixes(config)
    exempt = exempt_tokens(config)
    roots = source_roots(config)

    repairs: list[tuple[str, str]] = []
    declines: list[tuple[str, str, str]] = []
    for cited in extract_citations(text)["paths"]:
        if cited in exempt:
            continue
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        if any(rel.startswith(p) for p in prefixes):
            continue
        if _resolves(rel, repo_root, files, docs_dir, build_dir, roots):
            continue
        if _is_gitignored(repo_root, rel):
            continue

        candidates = suffix_candidates(rel, files)
        if len(candidates) != 1:
            # Ambiguity and zero-match both fail closed. Corroboration narrows
            # the entry condition; it does not resolve ambiguity, so a second
            # candidate still leaves the page untouched and blocking.
            continue
        candidate = candidates[0]
        if candidate not in corroborators:
            # Match the CANDIDATE, never the cited token: the token is what the
            # agent wrote, so corroborating it would be circular.
            declines.append((cited, candidate, "uncorroborated"))
            continue
        repairs.append((cited, candidate))

    new_text = text
    for old, new in repairs:
        new_text = rewrite_token(new_text, old, new)
    return new_text, repairs, declines

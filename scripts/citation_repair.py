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

    Rung 1 (edits, git-authoritative): the LINTER'S OWN VIEW of the prior
    committed page — `extract_citations(prior_text)["paths"]` intersected with
    the tracked set. Only a path `citation_exists` actually VALIDATED on that
    page evidences that the pipeline accepted a reference to that file.

    Deliberately NOT a raw substring scan of the prior text. A raw scan sees
    more path tokens than extract_citations does, and that surplus is exactly
    what disqualifies it: those tokens are invisible to extract_citations
    BECAUSE citation_exists never validates them — inside fenced blocks
    ("fenced examples are legitimately hypothetical", its own docstring),
    inside URL bodies, inside HTML comments, and as substrings of longer
    paths. A token the linter never checked evidences nothing about
    acceptance. Concretely: a prior page naming a path only inside a ```text
    fence would corroborate a new page's invented citation of the same tail,
    turning a block into a pass — the defect this module exists to prevent.
    Calling extract_citations also inherits the linter's fence semantics for
    free, satisfying import-never-reimplement rather than straining it.

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
        out |= set(extract_citations(prior_text)["paths"]) & files
    return out


def _excluded_reason(
    token: str,
    rel: str,
    repo_root: Path,
    exempt: set[str],
    prefixes: tuple[str, ...],
) -> str | None:
    """Which class `citation_exists` declines to CHECK this path as, if any.

    ONE definition, applied to BOTH ends of a repair: the cited token and the
    candidate it would be rewritten to. Every class here is unresolvable BY
    DESIGN, so a path in one of them evidences nothing and must never be
    written into a page.

    `_resolves` is deliberately not one of these classes. On the cited side it
    is the entry condition (a token that resolves needs no repair); on the
    candidate side it is vacuous (a candidate comes from the tracked set, so it
    always resolves). Callers apply it themselves.

    Ordering: on the cited side this runs AFTER `_resolves`, so the
    `_is_gitignored` subprocess is only paid for paths that do not resolve.
    """
    if token in exempt:
        return "exempt_token"
    if any(rel.startswith(p) for p in prefixes):
        return "example_namespace"
    if _is_gitignored(repo_root, rel):
        return "gitignored"
    return None


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

    Indices are over text.splitlines() — what strip_fenced_blocks iterates and
    what rewrite_token iterates — so the mirror is real. splitlines() is NOT
    text.split("\n"): six characters survive Path.read_text()'s universal-
    newline translation yet ARE splitlines() boundaries (U+2028, U+2029,
    \x85, \x0b, \x0c, \x1c; \r is safe, read_text normalises it). With any of
    them present, a split("\n") walk sees a fence opener glued to the end of
    the preceding line, never opens the fence, and returns nothing — while
    extract_citations, on splitlines(), strips that fence correctly. The
    divergence let rewrite_token rewrite the fenced illustration, turning a
    deliberate example into a false claim about real code.

    _INLINE_CODE_RE excludes newlines, so no code span the LINTER sees can
    straddle a line and per-line rewriting is equivalent: strip_fenced_blocks
    rejoins its surviving lines with "\n", so a span straddling one of the six
    reads as containing a newline there too, and matches in neither place.
    """
    fenced: set[int] = set()
    in_fence = False
    fence = ""
    start = 0
    for i, line in enumerate(text.splitlines()):
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

    Lines come from splitlines(), which is what _closed_fence_lines indexes and
    what strip_fenced_blocks iterates. They are rejoined by concatenating each
    line with its OWN terminator, taken from splitlines(keepends=True) —
    "\n".join() would be lossy, because splitlines() also splits on U+2028,
    U+2029, \x85, \x0b, \x0c and \x1c, and joining with "\n" would silently
    rewrite every one of those bytes. A line this function does not rewrite is
    emitted verbatim, so byte identity holds for pages that contain them.
    """

    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        if _SUFFIX_RE.sub("", token.strip()) != old:
            return match.group(0)
        return "`" + token.replace(old, new, 1) + "`"

    fenced = _closed_fence_lines(text)
    bodies = text.splitlines()
    raws = text.splitlines(keepends=True)
    out: list[str] = []
    for i, body in enumerate(bodies):
        if i in fenced:
            out.append(raws[i])
            continue
        out.append(_INLINE_CODE_RE.sub(_sub, body) + raws[i][len(body) :])
    return "".join(out)


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

    Those classes are tested on BOTH ends of a repair — see _excluded_reason.
    Testing the cited token alone let a repair MOVE a citation into an excluded
    class rather than out of one, which is the same harm in the other
    direction.
    """
    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    prefixes = example_prefixes(config)
    exempt = exempt_tokens(config)
    roots = source_roots(config)

    repairs: list[tuple[str, str]] = []
    declines: list[tuple[str, str, str]] = []
    for cited in extract_citations(text)["paths"]:
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        if _resolves(rel, repo_root, files, docs_dir, build_dir, roots):
            continue
        if _excluded_reason(cited, rel, repo_root, exempt, prefixes) is not None:
            continue

        candidates = suffix_candidates(rel, files)
        if len(candidates) != 1:
            # Ambiguity and zero-match both fail closed. Corroboration narrows
            # the entry condition; it does not resolve ambiguity, so a second
            # candidate still leaves the page untouched and blocking.
            continue
        candidate = candidates[0]

        # The same exclusions, applied to the CANDIDATE. Testing only the
        # cited token let a repair MOVE a citation into an excluded class:
        # cited `auth/session.py` with a corroborated `example/auth/session.py`
        # was rewritten into the reserved namespace, where check_path skips it
        # permanently and it is never verified again. A candidate in any
        # excluded class is declined, never repaired, under its own reason.
        cand_rel = _relativize(candidate, repo_root)
        why = (
            "outside_repo"
            if cand_rel is None
            else _excluded_reason(candidate, cand_rel, repo_root, exempt, prefixes)
        )
        if why is not None:
            declines.append((cited, candidate, f"candidate_{why}"))
            continue

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

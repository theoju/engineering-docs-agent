"""Deterministic repair of shortened citation paths (CCE-141).

`page-author` sometimes emits a citation as a bare relative path — the
committed page cited
`.claude/skills/connector-builder/references/checklist.md` at three sites and
the rewrite shortened it to `references/checklist.md`. `citation_exists`
correctly finds nothing at the repo root and blocks the page; post-CCE-140 the
deferral skip then abandons the PR, so the page is silently never written.

This module repairs the observable defect regardless of what causes it. The
safety argument is that a path is always a suffix of itself: if the page cited
`X` and now cites `suffix(X)`, that suffix necessarily matches `X`, so a UNIQUE
match is provably `X`. Repair cannot silently retarget a citation. Ambiguity
and zero-match both leave the page untouched and blocking, so repair can only
ever convert a block into a correct citation — never into a silent pass.

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
)


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

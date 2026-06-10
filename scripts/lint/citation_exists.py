"""Lint rule: citation_exists (CCE-110, Tier-1).

Verifies that repo artifacts cited in a page's PROSE actually exist: inline
code spans naming repo paths (`scripts/foo.py`, optional `:line` /
`:start-end` suffix) or test identifiers (`test_snake_case`). Confabulated
pages cite tests/files that were never written; this rule blocks them.

Scope notes:
- Fenced code blocks are stripped first — fenced examples are legitimately
  hypothetical. Only inline code spans in prose are checked.
- Distinct from capability C1 (scripts/verify_citations.py), which verifies
  pinned `path:line` + `<!--pin:TOKEN-->` citations on existing pages. This
  rule needs no pins and checks bare existence on newly authored pages.
- Generic-first degradation: when the config's directory is not inside a git
  repo, every path passes trivially (we cannot verify; we never block).
- The extraction functions are imported by scripts/orchestrator_runner.py
  (fact-checker dispatch). They are a shared-helper contract: grep callers
  repo-wide before changing signatures (CLAUDE.md).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RULE_NAME = "citation_exists"
SEVERITY = "block"

_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_TEST_ID_RE = re.compile(r"^test_[a-z0-9_]+$")
# dir/file.ext with optional :line or :start-end suffix; leading / allowed
# (absolute paths are relativized or skipped at verification time).
_REPO_PATH_RE = re.compile(r"^[\w.\-/]+/[\w.\-]+\.\w{1,8}(?::\d+(?:-\d+)?)?$")
_LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")
_PLACEHOLDER_MARKERS = ("<", ">", "*", "{", "}", "YYYY", "...")


def strip_fenced_blocks(text: str) -> str:
    """Drop ``` / ~~~ fenced regions; return the remaining prose lines."""
    out: list[str] = []
    in_fence = False
    fence = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence = True, stripped[:3]
            continue
        if in_fence and stripped.startswith(fence):
            in_fence = False
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def _is_placeholder(token: str) -> bool:
    return (
        any(m in token for m in _PLACEHOLDER_MARKERS)
        or token.startswith(("~", "$"))
        or "://" in token
    )


def extract_citations(text: str) -> dict[str, list[str]]:
    """Citations in prose, deduped in document order.

    Returns {"paths": [...], "tests": [...]} — repo-path tokens have any
    trailing :line suffix stripped.
    """
    paths: list[str] = []
    tests: list[str] = []
    for token in _INLINE_CODE_RE.findall(strip_fenced_blocks(text)):
        token = token.strip()
        if not token or _is_placeholder(token):
            continue
        if _TEST_ID_RE.match(token):
            if token not in tests:
                tests.append(token)
        elif _REPO_PATH_RE.match(token):
            bare = _LINE_SUFFIX_RE.sub("", token)
            if bare not in paths:
                paths.append(bare)
    return {"paths": paths, "tests": tests}

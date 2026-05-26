"""Diagram render gate (capability C3).

Build-time-only gate: proves agent-emitted Mermaid actually renders in the
built MkDocs site. The pass/fail verdict logic (fence scan, URL mapping,
ledger) is pure stdlib and always testable; the DOM measurement and browser
self-test require Playwright (a docs-tooling dependency) and are isolated
behind a guarded import. This module MUST NEVER be imported by the stdlib
agent runtime.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright  # noqa: F401

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # docs-tooling dep; absent in the agent runtime / local dev
    sync_playwright = None
    _PLAYWRIGHT_AVAILABLE = False

# An opening Mermaid fence at column 0 (mirrors scripts/lint/diagrams.py).
_MERMAID_FENCE = re.compile(r"^```mermaid\s*$", re.MULTILINE)


def scan_mermaid_sources(source_dir: Path) -> dict[str, int]:
    """Map each source page (POSIX path relative to source_dir) to its count
    of opening ``` ```mermaid ``` fences. Pages with no fence are omitted.
    Never raises; unreadable files are skipped.
    """
    out: dict[str, int] = {}
    if not source_dir.is_dir():
        return out
    for md in sorted(source_dir.rglob("*.md")):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        count = len(_MERMAID_FENCE.findall(text))
        if count:
            out[md.relative_to(source_dir).as_posix()] = count
    return out


def source_to_built_urls(page: str) -> list[str]:
    """Candidate built-site relative paths for a source page, probing both
    MkDocs layouts. ``foo/bar.md`` -> ``[foo/bar/index.html, foo/bar.html]``;
    an ``index.md`` -> its directory's ``index.html``.
    """
    stem = page[:-3] if page.endswith(".md") else page
    name = stem.rsplit("/", 1)[-1]
    if name == "index":
        return [
            f"{stem}.html"
        ]  # index.md -> index.html ; foo/index.md -> foo/index.html
    return [f"{stem}/index.html", f"{stem}.html"]

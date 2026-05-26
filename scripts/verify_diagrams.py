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


def _page_failure(page: str, expected: int, result: dict) -> dict | None:
    """Decide the single failure for one page from its measured result, or
    None if the page is clean. Precedence (first match wins): page_missing ->
    error_box -> asset_error -> count_mismatch. Pure; never raises.
    """
    if result.get("http_status") != 200:
        return {
            "page": page,
            "reason": "page_missing",
            "http": result.get("http_status"),
        }
    errors = result.get("error_boxes") or []
    if errors:
        return {"page": page, "reason": "error_box", "detail": errors[0]}
    assets = result.get("asset_errors") or []
    if assets:
        return {"page": page, "reason": "asset_error", "detail": assets[0]}
    rendered = int(result.get("rendered_ok") or 0)
    if rendered < expected:
        return {
            "page": page,
            "reason": "count_mismatch",
            "expected": expected,
            "rendered": rendered,
        }
    return None


def build_ledger(self_test: dict, page_results: list[dict]) -> dict:
    """Assemble the JSON ledger from the self-test outcome and per-page results.
    Each page_result is {page, expected, rendered_ok, failure(dict|None)}.
    """
    failures = [r["failure"] for r in page_results if r.get("failure")]
    return {
        "self_test": self_test,
        "checked_pages": len(page_results),
        "expected_diagrams": sum(int(r.get("expected") or 0) for r in page_results),
        "rendered_diagrams": sum(int(r.get("rendered_ok") or 0) for r in page_results),
        "failures": failures,
    }


def ledger_ok(ledger: dict) -> bool:
    """The gate passes iff the self-test held and no page failed."""
    return bool(ledger.get("self_test", {}).get("ok")) and not ledger.get("failures")

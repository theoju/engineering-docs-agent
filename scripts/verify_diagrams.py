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
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
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


# ---------------------------------------------------------------------------
# Browser layer (requires Playwright — guarded by _PLAYWRIGHT_AVAILABLE)
# ---------------------------------------------------------------------------

# In-page measurement: per .mermaid element, does it carry a real <svg> with
# non-zero geometry and NO Mermaid error signature? Returns one dict per element.
_MEASURE_JS = r"""
() => {
  const els = Array.from(document.querySelectorAll('.mermaid, pre.mermaid'));
  return els.map(el => {
    const svg = el.querySelector('svg');
    const box = svg ? svg.getBoundingClientRect() : {width: 0, height: 0};
    const txt = (el.textContent || '');
    const hasError =
      /syntax error/i.test(txt) ||
      el.querySelector('[class*="error"]') !== null ||
      (svg && /error/i.test(svg.getAttribute('aria-roledescription') || ''));
    return { hasSvg: !!svg, w: box.width, h: box.height, hasError };
  });
}
"""


@contextmanager
def _serve(site_dir: Path):
    """Serve site_dir on an ephemeral localhost port for the duration of the
    context. Yields the base URL (http://127.0.0.1:<port>)."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(site_dir))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def _assert_page(page_obj, url: str) -> dict:
    """Load url, wait for Mermaid to settle, and measure every .mermaid element.
    Captures same-origin 4xx/5xx responses as asset errors."""
    asset_errors: list[str] = []

    def _on_response(resp):
        if resp.status >= 400 and resp.url.startswith("http://127.0.0.1"):
            name = resp.url.rsplit("/", 1)[-1] or resp.url
            asset_errors.append(f"{name} {resp.status}")

    page_obj.on("response", _on_response)
    resp = page_obj.goto(url, wait_until="load")
    http_status = resp.status if resp else 0
    # Give Mermaid time to render (or to inject its error box).
    page_obj.wait_for_timeout(1500)
    measured = page_obj.evaluate(_MEASURE_JS)
    page_obj.remove_listener("response", _on_response)
    rendered_ok = sum(
        1
        for m in measured
        if m["hasSvg"] and m["w"] > 0 and m["h"] > 0 and not m["hasError"]
    )
    error_boxes = ["Syntax error in text" for m in measured if m["hasError"]]
    return {
        "http_status": http_status,
        "rendered_ok": rendered_ok,
        "error_boxes": error_boxes,
        "asset_errors": asset_errors,
    }


@contextmanager
def _browser_page(site_dir: Path):
    """Yield (base_url, page) with a Chromium page bound to a server for site_dir."""
    with _serve(site_dir) as base_url, sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            yield base_url, browser.new_page()
        finally:
            browser.close()


def _render_one(site_dir: Path, rel_url: str) -> dict:
    """Convenience: measure a single page (used by run_self_test and tests)."""
    with _browser_page(site_dir) as (base_url, page):
        return _assert_page(page, f"{base_url}/{rel_url}")


def run_self_test(fixtures_dir: Path) -> dict:
    """Phase A handshake: the known-good fixture must PASS and the known-broken
    fixture must FAIL through the very assertion path the real site uses. If the
    invariant does not hold (esp. broken passing), ok=False and the gate refuses
    to certify the site."""
    if not _PLAYWRIGHT_AVAILABLE:
        return {"good": "skip", "broken": "skip", "ok": False}
    good = _render_one(fixtures_dir, "good.html")
    broken = _render_one(fixtures_dir, "broken.html")
    good_pass = _page_failure("good.html", 1, good) is None
    broken_fail = _page_failure("broken.html", 1, broken) is not None
    return {
        "good": "pass" if good_pass else "fail",
        "broken": "fail" if broken_fail else "pass",
        "ok": good_pass and broken_fail,
    }


def verify_site(site_dir: Path, source_dir: Path, fixtures_dir: Path) -> dict:
    """Full gate: Phase A self-test handshake, then Phase B per-page verification
    of every source page that declares a Mermaid fence."""
    self_test = run_self_test(fixtures_dir)
    expected = scan_mermaid_sources(source_dir)
    page_results: list[dict] = []
    if expected:
        with _browser_page(site_dir) as (base_url, page):
            for src_page, count in sorted(expected.items()):
                candidates = source_to_built_urls(src_page)
                result = {
                    "http_status": 0,
                    "rendered_ok": 0,
                    "error_boxes": [],
                    "asset_errors": [],
                }
                for rel in candidates:  # probe both URL layouts; first 200 wins
                    result = _assert_page(page, f"{base_url}/{rel}")
                    if result["http_status"] == 200:
                        break
                page_results.append(
                    {
                        "page": src_page,
                        "expected": count,
                        "rendered_ok": result["rendered_ok"],
                        "failure": _page_failure(src_page, count, result),
                    }
                )
    return build_ledger(self_test, page_results)

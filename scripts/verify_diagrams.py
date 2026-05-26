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
        return [f"{stem}.html"]
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

# Mermaid renders asynchronously; wait until every .mermaid element has either
# produced an <svg> or surfaced an error, rather than sleeping a fixed interval
# (a flat sleep risks a FALSE count_mismatch on a slow CI runner). A page with no
# diagram / no loader script never settles and times out -> we then measure as-is.
_RENDER_SETTLED_JS = r"""
() => {
  const els = Array.from(document.querySelectorAll('.mermaid, pre.mermaid'));
  if (els.length === 0) return true;
  return els.every(el =>
    el.querySelector('svg') ||
    /syntax error/i.test(el.textContent || '') ||
    el.querySelector('[class*="error"]') !== null
  );
}
"""

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
    return { hasSvg: !!svg, w: box.width, h: box.height, hasError,
             errText: hasError ? txt.trim().slice(0, 120) : "" };
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
    Captures same-origin 4xx/5xx responses as asset errors. Never raises: a
    navigation/runtime error is recorded as a failed page (http_status 0)."""
    asset_errors: list[str] = []

    def _on_response(resp):
        if resp.status >= 400 and resp.url.startswith("http://127.0.0.1"):
            name = resp.url.rsplit("/", 1)[-1] or resp.url
            asset_errors.append(f"{name} {resp.status}")

    page_obj.on("response", _on_response)
    try:
        resp = page_obj.goto(url, wait_until="load")
        http_status = resp.status if resp else 0
        try:
            page_obj.wait_for_function(_RENDER_SETTLED_JS, timeout=5000)
        except Exception:
            pass  # blank/no-loader page never settles — measure as-is
        measured = page_obj.evaluate(_MEASURE_JS)
    except Exception as exc:  # navigation/runtime failure -> recorded, not raised
        return {
            "http_status": 0,
            "rendered_ok": 0,
            "error_boxes": [],
            "asset_errors": [str(exc)],
        }
    finally:
        page_obj.remove_listener("response", _on_response)
    rendered_ok = sum(
        1
        for m in measured
        if m["hasSvg"] and m["w"] > 0 and m["h"] > 0 and not m["hasError"]
    )
    error_boxes = [
        m.get("errText") or "mermaid error" for m in measured if m["hasError"]
    ]
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
    # Don't scan/load if the gate can't prove itself (self-test failed) or
    # Playwright is unavailable — returning here avoids calling sync_playwright()
    # (which is None without Playwright) and never certifies on a failed handshake.
    if not _PLAYWRIGHT_AVAILABLE or not self_test["ok"]:
        return build_ledger(self_test, [])
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


_FIXTURES_DIR = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "diagrams" / "render"
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify Mermaid diagrams render in the built site."
    )
    ap.add_argument("--site-dir", type=Path, required=True, help="built MkDocs site")
    ap.add_argument(
        "--source-dir", type=Path, required=True, help="docs source scanned for fences"
    )
    ap.add_argument(
        "--fixtures-dir", type=Path, default=_FIXTURES_DIR, help="self-test fixtures"
    )
    ap.add_argument(
        "--self-test-only", action="store_true", help="run only the Phase A handshake"
    )
    ap.add_argument(
        "--require",
        action="store_true",
        help="hard-fail if Playwright is unavailable (CI sets this)",
    )
    ap.add_argument("--json", action="store_true", help="emit the full JSON ledger")
    args = ap.parse_args(argv)

    if not _PLAYWRIGHT_AVAILABLE:
        msg = (
            "diagram gate unavailable: install docs tooling with "
            "`pip install -r requirements-docs.txt && playwright install chromium`"
        )
        if args.require:
            print(msg, file=sys.stderr)
            return 2
        print(msg)  # local convenience: skip, not fail
        return 0

    if args.self_test_only:
        st = run_self_test(args.fixtures_dir)
        print(
            json.dumps({"self_test": st}, indent=2) if args.json else f"self_test={st}"
        )
        return 0 if st["ok"] else 1

    ledger = verify_site(args.site_dir, args.source_dir, args.fixtures_dir)
    if args.json:
        print(json.dumps(ledger, indent=2))
    else:
        print(
            f"self_test_ok={ledger['self_test']['ok']} "
            f"pages={ledger['checked_pages']} expected={ledger['expected_diagrams']} "
            f"rendered={ledger['rendered_diagrams']} failures={len(ledger['failures'])}"
        )
    return 0 if ledger_ok(ledger) else 1


if __name__ == "__main__":
    raise SystemExit(main())

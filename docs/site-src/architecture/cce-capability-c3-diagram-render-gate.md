---
description: Build-time render gate that loads each built page in headless Chromium and confirms every declared Mermaid fence rendered to a real SVG with non-zero geometry — the second of two Mermaid validation layers (fence-syntax lint is the first).
source_files:
  - scripts/lint/diagrams.py
  - scripts/verify_citations.py
  - scripts/verify_diagrams.py
  - scripts/verify_docs_diagrams.py
last_reviewed: "2026-05-28"
status: draft
---

# CCE Capability C3 — Diagram Render Gate

Capability C3 proves that every Mermaid diagram declared in the docs source actually renders in the built MkDocs site. It runs at build time as a post-build gate, distinct from the lint-time fence check.

## Two-layer validation

There are two independent checks for Mermaid content. Run them both.

**Layer 1 — fence syntax lint** (`scripts/lint/diagrams.py`): runs during the standard lint pass, before the site builds. It verifies every ` ```mermaid ` fence has a matching closing ` ``` ` fence. Severity is `block`; an unterminated fence fails the lint run before any build work starts.

**Layer 2 — render gate** (`scripts/verify_diagrams.py`): runs after `mkdocs build`. It launches a headless Chromium browser via Playwright, loads each built page that declared a Mermaid fence, and confirms the SVG rendered with non-zero geometry and no Mermaid error signature.

## How the render gate works

The gate runs in two phases.

**Phase A — self-test handshake.** Before touching the real site, the gate loads two fixture pages: a known-good diagram that must pass and a known-broken diagram that must fail. If the broken fixture passes (or the good one fails), the gate refuses to certify the site and exits non-zero. This catches regressions in the measurement logic itself before they produce false-green results in CI.

**Phase B — per-page verification.** The gate calls `scan_mermaid_sources` to collect every source page that contains at least one ` ```mermaid ` fence, maps each to its built-site URL via `source_to_built_urls` (probing both MkDocs URL layouts), and loads each URL in the shared browser page. For each `.mermaid` element it waits for rendering to settle (async), then measures SVG geometry and checks for error signatures.

A page fails for one of four reasons, checked in order: `page_missing` (HTTP status ≠ 200), `error_box` (Mermaid rendered an error node), `asset_error` (a 4xx/5xx on a same-origin asset), `count_mismatch` (fewer rendered SVGs than declared fences).

## JSON ledger

`verify_site` (and the CLI with `--json`) emits a ledger:

```json
{
  "self_test": { "good": "pass", "broken": "fail", "ok": true },
  "checked_pages": 3,
  "expected_diagrams": 5,
  "rendered_diagrams": 5,
  "failures": []
}
```

`ledger_ok` returns `True` only when `self_test.ok` is true and `failures` is empty.

## Running it

```bash
# Full gate (Phase A + Phase B)
python scripts/verify_diagrams.py \
  --site-dir site/ \
  --source-dir docs/site-src/ \
  --json

# Phase A only (useful for smoke-testing the Playwright install)
python scripts/verify_diagrams.py \
  --site-dir site/ \
  --source-dir docs/site-src/ \
  --self-test-only

# Hard-fail if Playwright is not installed (set this in CI)
python scripts/verify_diagrams.py \
  --site-dir site/ \
  --source-dir docs/site-src/ \
  --require
```

## Playwright dependency

The render gate is intentionally isolated from the agent stdlib runtime. `sync_playwright` is imported inside a `try/except ImportError` block; the rest of the module uses only stdlib. Import this module from agent code and nothing breaks. Without Playwright, `verify_site` returns a ledger with `self_test.ok = False` and no page results — the gate is skipped, not crashed.

Install the docs tooling when you need the gate:

```bash
pip install -r requirements-docs.txt
playwright install chromium
```

In CI, pass `--require` so a missing Playwright install is a hard failure rather than a silent skip.

## Fence syntax rule details

`scripts/lint/diagrams.py` is the Tier-1 lint rule, rule name `diagrams`. It is enabled by default when the host config sets `lint.tier1: default`. The rule scans each file for `^```mermaid` fences and checks each one has a downstream `^``` ` close. An unterminated fence returns severity `block` and the lint runner stops the pipeline.

## Related capabilities

`scripts/verify_citations.py` implements Capability C1 — file:line citation verification. Citations use the pattern `` `path:line` <!--pin:TOKEN--> ``; the verifier classifies each as `ok`, `relocated`, `ambiguous`, or `gone`, and can auto-fix `relocated` citations with `--fix`. C1 and C3 are both post-author verification passes; C1 runs on the source tree, C3 runs on the built site.

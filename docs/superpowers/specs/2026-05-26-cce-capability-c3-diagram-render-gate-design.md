# Capability C3 — Diagram render gate

**Status:** approved 2026-05-26 (brainstorm + 3 locked decisions); implementation plan next.
**Jira:** CCE-30 (Sub-task under CCE-26; CCE-23 Phase 2). Final Capability C sub-piece.
**Parent design:** `docs/superpowers/specs/2026-05-25-cce-capability-c-canonical-core-citations-design.md` — C3 section (lines 118–128). This document is C3's full, implementable design.
**Reference impl:** ADIS (`advanced-data-importer`) `scripts/verify_docs_diagrams.py`, generalized off its hardcoded `docs/site-src` paths.

---

## Why this exists

C1 makes `file:line` citations verifiable. C2 authors canonical-core pages but emits **no diagrams** — it explicitly defers them to C3. C3 is the gate that lets diagrams back in safely: it proves that agent-emitted Mermaid **actually renders** in the built site, rather than trusting that a syntactically-plausible fence produces a picture.

The repo already has a cheap syntactic check — `scripts/lint/diagrams.py` validates Mermaid _fence_ well-formedness in the stdlib agent runtime. That catches an unterminated fence; it cannot catch a diagram that parses as a fence but fails to render (bad Mermaid grammar, a missing local asset, a diagram dropped during the build). C3 is the heavier _does-it-actually-render_ layer that runs at build time.

This is the umbrella spec's "one hard, testable gate": agent-emitted Mermaid that does not render fails the build.

## The hard constraint: runtime isolation

The gate requires Playwright + Chromium. It **must never enter the stdlib+pyyaml agent runtime.** The nightly orchestrator and its agents stay browser-free. C3 is a docs-build gate (CI + `make`), never an orchestrator stage.

The isolation is enforced mechanically, not by convention:

- The gate is the **only** module that imports `playwright`, at module top — so any accidental agent-runtime import fails loudly instead of silently dragging Chromium in.
- A stdlib test asserts that importing the agent entrypoints (`orchestrator_runner` and the agent dispatch path) never imports `playwright`.
- Playwright lives in a dedicated `requirements-docs.txt`, separate from the agent runtime deps (which stay stdlib + pyyaml).

## Architecture

One standalone CLI, `scripts/verify_diagrams.py` (naming mirrors C1's `scripts/verify_citations.py`), split into two layers so almost all of it is deterministically unit-testable without a browser:

| Layer                    | Responsibility                                                                                                                                           | Tested                                                                           |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| **Pure (stdlib)**        | scan source `.md` for ` ```mermaid ` fences → expected `{page: count}`; map each page to its built URL; classify per-page results; build the JSON ledger | always, in the normal suite                                                      |
| **Browser (Playwright)** | serve the built site on an ephemeral `http.server` port; drive Chromium; assert rendering; capture local-asset network status                            | `pytest.importorskip("playwright")` — skips in the normal suite, runs in docs CI |

The pure layer carries the logic; the browser layer is a thin driver. This keeps the deterministically-tested surface large and the Playwright-only surface small.

### CLI

```
python scripts/verify_diagrams.py --site-dir <built-site> --source-dir <docs_dir> [--json] [--self-test-only]
```

- `--site-dir` — the **built** MkDocs output (e.g. `site/`). The gate verifies a built site; it does not build it. The workflow / `make` target runs `mkdocs build` first.
- `--source-dir` — the docs source tree (the configured `docs_dir`) scanned for Mermaid fences.
- `--json` — emit the JSON ledger to stdout.
- `--self-test-only` — run only the self-test handshake (Phase A) and exit; for wiring/debugging the gate itself.

Exit non-zero on any failure (self-test broken, unrendered diagram, count mismatch, local-asset 4xx/5xx, missing built page).

## The gate algorithm

### Phase A — self-test handshake (every run, before judging anything)

The gate ships two bundled HTML fixtures under `tests/fixtures/diagrams/`:

- `good.html` — a minimal page that loads Mermaid and contains one valid diagram.
- `broken.html` — the same page with an **invalid** Mermaid diagram (a syntax error), which Mermaid renders as its error box.

Phase A loads both through the _same_ browser + assertion path the real site uses, and asserts:

- `good.html` → **PASS**
- `broken.html` → **FAIL**

If that invariant does not hold — the good fixture fails, or (the dangerous case) the broken fixture passes — the gate exits non-zero with `self-test failed` and certifies nothing. **A gate that cannot demonstrate it still catches a broken diagram is treated as broken itself.**

### Phase B — site verification

1. **Expected set.** Scan every `.md` under `--source-dir` for ` ```mermaid ` opening fences; count per file → `{source_page: expected_count}`. A file with no fence is not in the set.
2. **Map to built URLs.** For each source page, resolve its built page in `--site-dir`, probing both MkDocs layouts: `foo/bar.md` → `foo/bar/index.html` (`use_directory_urls: true`, the default) or `foo/bar.html` (false). `index.md` maps to the section root.
3. **Load + assert per page** (via the local server):
   - **HTTP 200** for the page — a non-200 means the expected page was dropped from the build (nav removal, broken include); that is a failure, not a skip.
   - **rendered diagram count ≥ expected count** — catches a diagram that silently vanished during the build even though the page survived.
   - each rendered `.mermaid` element has a child `<svg>` with **non-zero** bounding box **and no Mermaid error signature** (no "Syntax error" text, no error-class `<g>`/`<svg>`). This is the false-pass guard: Mermaid's own error output _is_ a DOM element, so "element exists" is not sufficient.
   - **no local-asset 4xx/5xx** — any same-origin response with a 4xx/5xx status (CSS, JS, the Mermaid bundle, images) fails the page.
4. **Aggregate + ledger.** Collect per-page results; exit non-zero if any failed.

### JSON ledger

```json
{
  "self_test": { "good": "pass", "broken": "fail", "ok": true },
  "checked_pages": 0,
  "expected_diagrams": 0,
  "rendered_diagrams": 0,
  "failures": [
    {
      "page": "core/api/",
      "reason": "count_mismatch",
      "expected": 2,
      "rendered": 1
    },
    {
      "page": "core/storage/",
      "reason": "error_box",
      "detail": "Syntax error in text"
    },
    {
      "page": "guides/setup/",
      "reason": "asset_error",
      "detail": "main.css 404"
    },
    { "page": "core/gone/", "reason": "page_missing", "detail": "HTTP 404" }
  ]
}
```

`failures` empty ⇒ exit 0. Any entry ⇒ exit non-zero.

## CI / local integration

### `.github/workflows/docs.yml` (new) — the merge-blocking gate

Modeled on the existing `release.yml` / `test.yml`. Triggers on push/PR touching `docs_dir` **or** the gate's own files (`scripts/verify_diagrams.py`, the fixtures, `requirements-docs.txt`, the workflow). Steps:

1. checkout, set up Python
2. `pip install -r requirements-docs.txt`
3. `playwright install --with-deps chromium`
4. `mkdocs build --strict`
5. `python scripts/verify_diagrams.py --site-dir site --source-dir <docs_dir> --json`

Required status check → **blocks merge.** A missing Playwright/Chromium here is a hard failure (environment misconfiguration), never a silent skip. The per-PR `test.yml` stays Chromium-free.

### `make docs-verify` — local convenience

Builds the site and runs the gate. If `import playwright` fails, prints an install hint (`pip install -r requirements-docs.txt && playwright install chromium`) and exits 0 — **skip is local-only**, so a contributor without Chromium is not blocked from other work. CI never takes this skip path.

### Dependencies

`requirements-docs.txt` (new) declares Playwright (pinned), separate from the agent runtime. Per the umbrella Dependencies section, the setup skill (S) references this docs-tooling file; it is never merged into the agent runtime requirements.

## Generic-first & graceful degradation

Behavior is driven by CLI inputs and detection, never hardcoded paths:

- `--site-dir` / `--source-dir` are required CLI inputs; `docs.yml` derives `docs_dir` from the host config, the same way the rest of the plugin does.
- **No Mermaid anywhere** → expected set empty → Phase B passes trivially. Phase A still runs, proving the gate is functional even when there is nothing to check.
- **Playwright unavailable** → hard-fail in CI; graceful skip (exit 0 + message) for local `make docs-verify`.
- **A host with no docs site** → `docs.yml` only triggers on `docs_dir` changes, so it never runs where there is nothing to gate.

## Error handling & verification

- The gate is a **hard gate**: non-zero exit on any failure, surfaced as a required CI check.
- Self-test failure is itself a non-zero exit — the gate fails closed.
- Local skip is the only soft path, and only when Playwright is absent locally.

## Testing strategy

TDD throughout, fixture-driven (arbitrary-host fixtures, not this repo's tree).

**Pure-logic unit tests (stdlib, always run in the normal suite):**

- fence scanning: single fence, multiple fences in one file, indented fence, fence with info-string attrs, a ` ``` ` block that is _not_ mermaid (ignored), nested/embedded fence edge cases.
- URL mapping: `use_directory_urls` true and false; `index.md` → section root; nested paths.
- expected-count map: per-page counts; a no-fence file absent from the set.
- ledger shape: failures aggregate correctly; empty failures ⇒ exit 0.
- degradation: empty `--source-dir` scan ⇒ empty expected set.
- **isolation test:** importing `orchestrator_runner` / the agent dispatch path does not import `playwright`; `verify_diagrams` is standalone.

**Render tests (`pytest.importorskip("playwright")`; run in docs CI, skip locally without Playwright):**

- `good.html` fixture → page passes.
- `broken.html` fixture (invalid Mermaid) → page fails with `error_box`.
- blank / missing-`<svg>` diagram → fails.
- local-asset 404 fixture → fails with `asset_error`.
- **count cross-check:** a fixture whose source declares 2 fences but whose built page renders 1 → fails with `count_mismatch`.
- **self-test handshake:** `self_test()` returns good→pass / broken→fail; and the gate exits non-zero if the handshake is violated (simulated by pointing it at a fixture pair that breaks the invariant).

## Relationship to existing code

- **`scripts/lint/diagrams.py`** stays unchanged — the fast, stdlib, agent-runtime **syntactic** fence check. C3 is additive: syntax (cheap, every page, agent runtime) + render (heavy, build time, CI). Two layers, no overlap removed.
- **C2** can lift its diagram deferral once C3 lands: authored pages may carry Mermaid again, now backed by a render gate.

## What's left behind from ADIS

- ADIS's hardcoded `docs/site-src` site path and `REPO_URL_BASE` → replaced by `--site-dir` / `--source-dir` CLI inputs.
- ADIS's manual `drift-doc-*.png` screenshots — not a CI artifact; C3 produces a JSON ledger instead.
- ADIS's `verify_footnotes.sh` — out of scope; C's citation model is C1's pinned `file:line`, not footnotes.

## Sequencing & delivery

One implementation plan, executed via subagent-driven-development, landing on `feat/CCE-30-diagram-render-gate` as its own PR (base `main`). Completes Capability C. The new `docs.yml` is a required check that must go green on the PR before merge.

## Risks & open questions

- **Playwright in CI is heavy/slow.** Mitigation: `docs.yml` triggers only on `docs_dir` / gate-file changes; it is kept out of the per-PR `test.yml`.
- **Mermaid version drift in the error signature.** Mitigation: assert a _combination_ (non-zero geometry AND absence of error markers), and pin Mermaid via the built site's bundled version; the self-test's `broken.html` exercises the real error path each run, so a signature change surfaces as a self-test failure rather than a silent false-pass.
- **First-run `docs.yml` flakiness** (a brand-new Playwright workflow). Mitigation: `--self-test-only` allows validating the gate end-to-end in CI independent of site content; the self-test handshake makes "gate environment broken" distinguishable from "a diagram is broken."
- **URL-mapping mismatch** if a host uses a non-default MkDocs layout. Mitigation: probe both `use_directory_urls` layouts; a built page that resolves to neither is reported as `page_missing`, surfacing the mismatch instead of silently passing.

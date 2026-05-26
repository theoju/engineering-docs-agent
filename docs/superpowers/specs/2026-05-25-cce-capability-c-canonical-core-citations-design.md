# Capability C — Canonical Core + diagrams + verified `file:line` citations

**Status:** approved 2026-05-25; three per-ticket plans next (C1 → C2 → C3).
**Jira:** CCE-26 (Story; CCE-23 Phase 2). Per-subsystem implementation tickets created at plan time.
**Source:** generalized from ADIS (`advanced-data-importer`) — `scripts/{verify_docs_diagrams,audit_docs,build_doc_source_map}.py`, `scripts/verify_footnotes.sh`, and the `docs/site-src/core/**` canonical pages.
**Predecessor:** `docs/superpowers/specs/2026-05-24-structured-docs-site-generation-design.md` (umbrella) names C as "Canonical Core + diagrams (Phase 2)". This spec is C's full design.

---

## Why this exists

Phase 1 (S + D + API + M) ships a themed, navigable site with a Decision Archive, API reference, and a file-level doc↔source map. What it lacks is a **human-readable architecture narrative that stays honest against the code**: component-organized pages that explain the system in present tense, cite their evidence precisely, and carry diagrams that are verified to render.

ADIS built exactly this and is the reference implementation. The job here is to **reuse what ADIS got right and fix what it got wrong**, generalized so it runs on any host repo — not just ADIS or this repo.

## Scope: three subsystems, one spec, three plans

C decomposes into three subsystems that share frontmatter conventions and a drift posture but differ sharply in nature:

|        | Subsystem                      | Nature             | Runtime                          |
| ------ | ------------------------------ | ------------------ | -------------------------------- |
| **C1** | Verified `file:line` citations | Deterministic      | stdlib (agent + CLI)             |
| **C2** | Canonical Core authoring       | LLM, draft-scoped  | agent (page-author)              |
| **C3** | Diagram render gate            | Deterministic gate | **build-time only** (Playwright) |

One design spec (this document); three sequenced implementation plans. **C1 → C2 → C3.** C1 is the deterministic foundation C2's authoring emits into, and is independently shippable. C3 is an independent CI gate. Each lands on its own branch + PR (matching the CCE-23 stack pattern).

## The pivotal decision: the citation model

ADIS shipped **two** citation systems:

- **Footnotes** (`[^id]` → a document) — verified for intra-file reference↔definition integrity by `verify_footnotes.sh`, but coarse (no line) and the target's existence is never checked.
- **Raw `file:line` prose** (`base.py:148`) — written by the LLM against a pinned commit SHA, with **zero verification**. ADIS acknowledges these rot silently on any refactor.

A "file:line citations" capability that repeats ADIS's raw-prose approach inherits its rot. The design choice that defines C1: **keep literal `file:line` evidence, but make every citation verifiable** by pinning it to a short expected token. The line number becomes a _hint_; the token is the truth. That single change turns an unverifiable convention into a deterministic, self-healing one.

## C1 — Verified `file:line` citations

### Format

A citation in an authored page is an inline code span naming a repo-relative `path:line`, immediately followed by an HTML-comment **pin** carrying a short literal expected on that line:

```markdown
`BaseConnector` is defined at `backend/connectors/base.py:148` <!--pin:class BaseConnector-->
```

The pin renders invisibly in MkDocs. The token is a short, distinctive substring of the cited line (a signature fragment, class/def header, constant name) — not the whole line.

### `scripts/verify_citations.py` (new; stdlib only)

CLI: `--docs-dir <site-src> [--repo-root .] [--fix] [--strict] [--json]`.

For every citation+pin pair found under `docs_dir`, resolve `path` against `repo_root`, read line `L`, and classify:

| Condition                                                   | Class         | Action                                                          |
| ----------------------------------------------------------- | ------------- | --------------------------------------------------------------- |
| Token present at line `L`                                   | **ok**        | none                                                            |
| Token absent at `L`, present **uniquely** elsewhere at `L'` | **relocated** | report `L → L'`; with `--fix`, rewrite the citation in the page |
| Token present at **multiple** lines                         | **ambiguous** | report; page → review-needed (cannot safely auto-fix)           |
| Token absent entirely, or `path` missing                    | **gone**      | report; page → review-needed (cited claim invalidated)          |

Output is a JSON ledger:

```json
{
  "checked": 0,
  "ok": 0,
  "relocated": [{ "page": "...", "path": "...", "old": 148, "new": 161 }],
  "ambiguous": [
    { "page": "...", "path": "...", "token": "...", "lines": [12, 88] }
  ],
  "gone": [{ "page": "...", "path": "...", "token": "...", "line": 148 }],
  "pages_review_needed": ["core/backend/connectors.md"]
}
```

Exit 0 normally; non-zero only under `--strict` when any `gone`/`ambiguous` remain. `--fix` rewrites only `relocated` citations (the safe, unambiguous case).

### Orchestrator stage `verify-citations`

Runs immediately after M's `source-map` stage, mirroring M's `compute_source_drift` / `_drift_whats_new_lines`:

- **Auto-fix in-run:** apply `relocated` rewrites and commit them (the line genuinely moved; the claim is intact).
- **Surface drift:** `gone` + `ambiguous` pages appear under a **"Pages to review (citation drift)"** block in the What's-New entry and the notifier digest — the same review-needed posture M uses for source drift.
- **Best-effort / read-only-except-autofix:** an exception in the stage adds an info-only partial reason and never aborts the run.

The stage reuses M's `.doc-source-map.json` to verify only pages whose mapped source files changed in the processed PRs (the nightly fast path); the standalone CLI does a full scan (CI / `make`).

### Why this is the line-level extension of M

M maps page → source files and flags when a _mapped file changed_. C1 verifies the _specific lines_ a page cites within those files. They share the `source_files:` frontmatter, the `.doc-source-map.json` artifact, and the review-needed drift posture. C1 is M at finer granularity.

## C2 — Canonical Core authoring

The `page-author` agent synthesizes the configured archive sources into component-organized pages under the `core` section (`site-src/core/**`), **convention-aware**:

- **Convention present** (repo carries `docs/superpowers/{specs,plans}`): distill the specs/plans into present-tense component pages, reconcile claims against the mapped source, lift/adapt existing mermaid diagrams, and emit C1 pinned citations for concrete claims. Source docs are distilled, never reproduced verbatim.
- **Convention absent:** best-effort draft derived from the codebase alone, for the slice the repo doesn't already document.

Page frontmatter:

```yaml
---
description: <one-line purpose>
source_files:
  - path/to/file.py
last_reviewed: YYYY-MM-DD
status: draft
---
```

Every page is `status: draft` — reorganization, coverage gaps, and spec staleness all still want human eyes. **Content quality is not unit-tested** (per the umbrella spec); only the scaffolding, frontmatter shape, and draft status are asserted.

`scripts/audit_docs.py` is ported generalized (`--docs-dir`): for each page it runs `git log --since=<last_reviewed> -- <source_files>` and reports pages with churn — the periodic "what to re-review" nudge. It complements, not replaces, M (file drift) and C1 (line drift), which are the honest mechanical checks.

`site-src/core` joins `agent_editable_paths`; `docs/superpowers/**` stays **read-only input** (this is the umbrella spec's permanent fix for the dogfood defect where the agent rewrote raw process specs in place).

## C3 — Diagram render gate

Port ADIS's `scripts/verify_docs_diagrams.py` generalized (`--site-dir`, `--source-dir` are already CLI inputs). It serves the built MkDocs site on a local port, drives Playwright Chromium to load every page containing a ` ```mermaid ` block, and asserts each `.mermaid` element rendered — handling both the inline-SVG pattern (non-error `<svg>`) and the Material shadow-DOM pattern (non-zero bounding box). It fails on any local-asset 4xx/5xx. Exit non-zero on any unrendered diagram.

**Hard constraint:** this script requires Playwright + Chromium and **must never enter the stdlib+pyyaml agent runtime.** It runs as a docs-build gate:

- A new `.github/workflows/docs.yml` that builds the site and runs the gate on changes under `docs_dir` (modeled on the existing `release.yml` / `test.yml` patterns).
- A `make docs-verify` target for local use.
- Playwright/Chromium declared in the docs-tooling requirements file the setup skill (S) installs — separate from the agent runtime, per the umbrella Dependencies section.

This is the umbrella spec's "one hard, testable gate": agent-emitted mermaid that does not render fails the build.

## Generic-first and graceful degradation

Behavior is driven by `site:`/config + detection, never hardcoded paths:

- **No `core` sources** (no specs/plans, generic repo) → C2 takes the code-only fallback for the documented slice; if there is nothing to author, the section is skipped, not emitted empty.
- **No citations** in any page → `verify_citations.py` emits an empty ledger and exits clean.
- **No mermaid** in the built site → the diagram gate passes trivially.
- **Playwright unavailable** → the diagram gate reports "diagram gate unavailable" in CI and is skipped; it is never required in the agent runtime.

## Config & schema additions

- The `site:` `core` section already exists (generator `agent-authored`); C2 authors into it. No new section type required.
- A verify toggle (e.g. `lint.verified_citations` or a `citations:` block) gates whether the `verify-citations` stage auto-fixes vs report-only, validated at config load alongside the existing `site:` validation.
- Citation drift, like source drift, is surfaced in run state and the digest; no new state schema beyond the existing `partial_reasons` / What's-New shapes.

## Error handling & verification

- **C1:** deterministic and fully unit-tested. The stage is best-effort (info-only partial reason on exception); the CLI is the hard gate under `--strict` for CI.
- **C2:** `mkdocs build --strict` (broken links / nav) and the content-validator lint tiers continue to apply to authored pages. Content quality is not asserted.
- **C3:** the render gate is the hard, testable gate; build red on any unrendered diagram.

## Testing strategy

TDD throughout, fixture-driven (arbitrary-host fixtures, not this repo's tree; production CLI dispatch monkeypatched):

- **C1** — `verify_citations.py` against fixtures: exact match; moved-token auto-relocate (+ `--fix` rewrite); token-gone drift; ambiguous multi-match; missing file; no-citations clean exit. Plus an orchestrator-stage integration test mirroring `tests/orchestrator/test_source_map_stage.py` (auto-fix committed; gone/ambiguous surfaced in What's-New + digest).
- **C2** — scaffolding produces the expected `core/**` tree and frontmatter (`source_files`, `last_reviewed`, `status: draft`); content is not asserted.
- **C3** — the render gate passes for a valid-mermaid fixture and fails for a deliberately broken one (port ADIS's test).

## What's left behind from ADIS

- **Unverified raw `file:line` prose (System B)** — replaced by pinned + verified C1.
- **The 4-lens IA** (Portfolio / Future-me / Ops / Onboarding) and the `synthesized_into:` frontmatter field — ADIS-specific; no general consumer.
- **`generate_archive_indexes.py`'s promotion sets** (`PROMOTED_ADR_SLUGS`, `PROMOTED_SPEC_FILENAMES`) — ADIS migration scaffolding with no general equivalent.
- **The `drift-doc-*.png` artifacts** — manual screenshots, not CI outputs.
- Every ported script drops ADIS's hardcoded `docs/site-src` paths and `REPO_URL_BASE` for config/CLI inputs.

## Sequencing & delivery

Three plans, landed in sequence, each its own branch + PR + CCE ticket:

1. **C1 — verified citations.** Deterministic, highest-value, lowest-risk; independently shippable. Ships the format, `verify_citations.py`, and the orchestrator stage.
2. **C2 — Canonical Core authoring.** Builds on C1 (its pages emit pinned citations). Draft-scoped; content not unit-tested.
3. **C3 — diagram render gate.** Independent CI/build gate; adds the docs-tooling Playwright dependency and `docs.yml` workflow.

Each executes via subagent-driven-development. C2 and C3 do not block C1; C1 should land first because it is the foundation and the cleanest win.

## Risks & open questions

- **Pin token uniqueness.** A token that recurs in a file is `ambiguous` and can't auto-fix. Mitigation: authoring guidance to pick distinctive tokens (signature fragments, not bare keywords); the verifier reports ambiguity so it's visible, not silent.
- **C2 content unpredictability.** Mitigated by draft-status framing, C1's mechanical citation check, and shipping it separately from the deterministic C1.
- **Diagram-gate cost.** Playwright/Chromium is heavy; running it per-PR may be slow. Mitigation: trigger `docs.yml` only on `docs_dir` changes; keep it out of the per-PR `test.yml`.
- **Auto-fix commit noise.** In-run citation relocation produces commits on the docs PR. Acceptable (the alternative is stale citations); revisit batching if noise is high.

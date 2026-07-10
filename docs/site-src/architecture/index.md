---
title: Architecture
status: draft
description: Section landing page for architecture docs — component design, agent contracts, data flows, and system internals.
source_files:
  - scripts/orchestrator_runner.py
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/135
last_reviewed: "2026-07-10"
---

# Architecture

_Architecture: component design, agent contracts, data flows, and system internals._

As of PR #135, this page and its sibling architecture pages — [Lint Rules](lint-rules.md) and [Bootstrap fail-fast mechanisms](bootstrap-fail-fast.md) — carry the full `AGENT_AUTHORED_REQUIRED` frontmatter set (`description`, `source_files`, `last_reviewed`, `status`; see `scripts/frontmatter_contract.py`). All three predated the frontmatter contract and were missing those fields, so every nightly `page-author` edit to them failed Tier-1 `frontmatter_schema`/`description_quality` lint and was silently dropped as a `lint_block` partial reason — the exact failure mode observed in PR #134's edit to this page. With the fields in place, edits to these three pages now pass Tier-1 lint, which unblocks CCE-101's auto-merge gate (eligible = non-partial AND zero fact-checker warnings AND no human commits).

<!-- docs-agent:overview:start -->
**In this section**

- **Bootstrap fail-fast mechanisms** — The C2 bootstrap pipeline (CCE-38) adds four structural safeguards that catch bad artifacts before they reach the published site. Before this work, the pipeline trusted `page-author`'s `ok: true` signal without independently verifying the written file — allowing bad YAML, missing frontmatter, and thin descriptions to slip through undetected.
- **Lint Rules** — The lint runner (`scripts/lint/lint_runner.py`) validates agent-authored Markdown before it reaches the docs site. Rules are tiered: **block** rules prevent a page from being published; **warn** rules surface in the PR review but do not block it.
- **Orchestrator** — `scripts/orchestrator_runner.py:run()` is the nightly docs-agent pipeline. It turns a window of merged PRs (and, when configured, Jira issues) into a single `docs-agent/YYYY-MM-DD` PR. The pipeline is a sequence of dispatch loops — some mandatory, some advisory — each of which can go partial independently. This page documents the loop structure and, in detail, how the CCE-109/CCE-114 soft time budget is enforced across all of them.
- **Engineering Docs Agent** — A Claude Code plugin that turns merged PRs, Jira issues, and commits into a nightly docs-update PR — with voice-matched authoring, tiered linting, gap detection, and post-merge publish verification.
- **Capability C2: Canonical Core Authoring** — Capability C2 is the part of the engineering-docs-agent pipeline responsible for writing and maintaining canonical core documentation pages. It runs as the `page-author` subagent and produces files under the `agent-authored` site section. Every page C2 touches carries a machine-verifiable frontmatter contract that downstream lint, source-map, and publish-verification stages depend on.
- **CCE Capability C3 — Diagram Render Gate** — Capability C3 proves that every Mermaid diagram declared in the docs source actually renders in the built MkDocs site. It runs at build time as a post-build gate, distinct from the lint-time fence check.
- **CCE-10: Source Collector Canonical Shape** — The `source-collector` subagent feeds every downstream stage of the nightly pipeline. Its output must always validate against the canonical schema; a malformed response halts PR summarization, page authoring, and gap detection for the entire run.
- **CCE-12: Source-Collector Tool-Use Diagnostics** — CCE-12 added stream-json dispatch mode to `dispatch_subagent` so you can observe the exact tool-call sequence a subagent executes at runtime. The primary motivation was diagnosing why the source-collector agent's latency varied by 10–20× across runs — and confirming whether that variance was driven by tool calls or by the NDJSON parse overhead.
- **CCE-6 / 7 / 8 Batch: Dispatch and Orchestration Layer** — The CCE-6/7/8 batch landed the core dispatch infrastructure and the orchestrator run-loop that drives every nightly docs-PR. These changes are the spine of the pipeline: every subsequent capability (gap detection, page authoring, notifier) runs through the patterns established here.
- **GitHub Pages Publish Target (CCE-32)** — The engineering-docs-agent publishes docs sites to GitHub Pages using the Actions-source deploy mode. This page covers the workflow architecture, the Node 24 constraint, the `.nojekyll` invariant, and how the publish-verifier integrates with the deployed URL.
- **Schema Enforcement (CCE-4)** — Every subagent call is validated against a JSON schema before the orchestrator acts on its output. An invalid response records a specific reason in `partial_reasons` and lets the pipeline continue — it never crashes the run.
- **Structured Docs Site Generation** — The engineering-docs-agent produces a structured, navigable docs site by combining three layers: a per-run source map that links code to docs, archive indexes that make ADRs/specs/plans discoverable, and a diagram-verification pass that catches broken visuals before the PR lands.
- **Capability C — Canonical Core Citations** — Capability C keeps documentation honest about the code it describes. It has two
- **CCE-23: API Reference Generation** — CCE-23 adds a self-updating API reference section to any host repo's docs site. The setup skill scaffolds the section once; from then on, the three extractors regenerate their pages automatically at every `mkdocs build`.
- **Decision Archive Index Generator (CCE-23)** — The archive-index generator (`scripts/archive_indexes.py`) turns directories of date-prefixed Markdown files into navigable index pages. It is capability D of the docs-agent: a pure read-then-write step that runs on every nightly pass and always overwrites its output.
- **Source Map and Drift Detection (CCE-23)** — The source map (`scripts/source_map.py`) and drift detector (`scripts/source_drift.py`) together answer: when source code changes, which docs pages need a human review?

_16 pages · regenerated nightly_
<!-- docs-agent:overview:end -->

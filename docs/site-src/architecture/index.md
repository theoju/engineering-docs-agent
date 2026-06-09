---
title: Architecture
status: draft
---

# Architecture

_Architecture: component design, agent contracts, data flows, and system internals._

<!-- docs-agent:overview:start -->
**In this section**

- **Orchestrator: two-stage subagent output parse pipeline** — PR #75 introduced a `_strip_code_fence` helper that sits in front of the existing `_rescue_json_object` path inside `dispatch_subagent`. Together they form a two-stage pipeline for turning raw subagent output into parsed JSON.
- **Bootstrap fail-fast mechanisms** — The C2 bootstrap pipeline (CCE-38) adds four structural safeguards that catch bad artifacts before they reach the published site. Before this work, the pipeline trusted `page-author`'s `ok: true` signal without independently verifying the written file — allowing bad YAML, missing frontmatter, and thin descriptions to slip through undetected.
- **Capability C — Canonical Core Citations** — Capability C keeps documentation honest about the code it describes. It has two
- **Capability C2: Canonical Core Authoring** — Capability C2 is the part of the engineering-docs-agent pipeline responsible for writing and maintaining canonical core documentation pages. It runs as the `page-author` subagent and produces files under the `agent-authored` site section. Every page C2 touches carries a machine-verifiable frontmatter contract that downstream lint, source-map, and publish-verification stages depend on.
- **CCE Capability C3 — Diagram Render Gate** — Capability C3 proves that every Mermaid diagram declared in the docs source actually renders in the built MkDocs site. It runs at build time as a post-build gate, distinct from the lint-time fence check.
- **CCE-10: Source Collector Canonical Shape** — The `source-collector` subagent feeds every downstream stage of the nightly pipeline. Its output must always validate against the canonical schema; a malformed response halts PR summarization, page authoring, and gap detection for the entire run.
- **CCE-12: Source-Collector Tool-Use Diagnostics** — CCE-12 added stream-json dispatch mode to `dispatch_subagent` so you can observe the exact tool-call sequence a subagent executes at runtime. The primary motivation was diagnosing why the source-collector agent's latency varied by 10–20× across runs — and confirming whether that variance was driven by tool calls or by the NDJSON parse overhead.
- **CCE-14: Source Collector Prompt Hardening** — CCE-14 investigated why source-collector output parsing failed in baseline runs. The investigation used stream-json diagnostics (built in CCE-12) to observe ground-truth tool-call sequences. It identified two root causes: `_extract_final_assistant_text` returning `""` when the model's final assistant turn contained only `tool_use` blocks, and a user-level plugin's `SessionStart` hook injecting "★ Insight" prose before the JSON output (addressed as CCE-15).
- **CCE-15: Source Collector Root Cause Sweep** — CCE-15 diagnosed two independent failure modes in the source-collector dispatch path that caused the orchestrator to silently misread subagent output. Both modes were confirmed in CCE-14 production runs. This page documents the root causes, the fixes, and the test coverage that pins each behavior.
- **CCE-23: API Reference Generation** — CCE-23 adds a self-updating API reference section to any host repo's docs site. The setup skill scaffolds the section once; from then on, the three extractors regenerate their pages automatically at every `mkdocs build`.
- **Decision Archive Index Generator (CCE-23)** — The archive-index generator (`scripts/archive_indexes.py`) turns directories of date-prefixed Markdown files into navigable index pages. It is capability D of the docs-agent: a pure read-then-write step that runs on every nightly pass and always overwrites its output.
- **Source Map and Drift Detection (CCE-23)** — The source map (`scripts/source_map.py`) and drift detector (`scripts/source_drift.py`) together answer: when source code changes, which docs pages need a human review?
- **GitHub Pages Publish Target (CCE-32)** — The engineering-docs-agent publishes docs sites to GitHub Pages using the Actions-source deploy mode. This page covers the workflow architecture, the Node 24 constraint, the `.nojekyll` invariant, and how the publish-verifier integrates with the deployed URL.
- **Schema Enforcement (CCE-4)** — Every subagent call is validated against a JSON schema before the orchestrator acts on its output. An invalid response records a specific reason in `partial_reasons` and lets the pipeline continue — it never crashes the run.
- **CCE-5 through CCE-9: Batch Prep Roadmap** — This page covers the architectural groundwork delivered across Jira tickets CCE-5 through CCE-9. Together they establish the orchestrator's runtime reliability: validated config/state loading, a dry-run test harness, and a releasable v0.1.0 baseline that subsequent capabilities build on.
- **CCE-6 / 7 / 8 Batch: Dispatch and Orchestration Layer** — The CCE-6/7/8 batch landed the core dispatch infrastructure and the orchestrator run-loop that drives every nightly docs-PR. These changes are the spine of the pipeline: every subsequent capability (gap detection, page authoring, notifier) runs through the patterns established here.
- **Engineering Docs Agent** — A Claude Code plugin that turns merged PRs, Jira issues, and commits into a nightly docs-update PR — with voice-matched authoring, tiered linting, gap detection, and post-merge publish verification.
- **Lint Rules** — The lint runner (`scripts/lint/lint_runner.py`) validates agent-authored Markdown before it reaches the docs site. Rules are tiered: **block** rules prevent a page from being published; **warn** rules surface in the PR review but do not block it.
- **Structured Docs Site Generation** — The engineering-docs-agent produces a structured, navigable docs site by combining three layers: a per-run source map that links code to docs, archive indexes that make ADRs/specs/plans discoverable, and a diagram-verification pass that catches broken visuals before the PR lands.
- **v0.1.1 Hardening** — v0.1.1 is a stabilization release. It tightens the contracts between pipeline stages, expands test coverage across the orchestrator and verification paths, and rounds out the Tier-1 lint rule set. No new capabilities are added; the focus is correctness under edge cases the initial release exposed.

_20 pages · regenerated nightly_
<!-- docs-agent:overview:end -->

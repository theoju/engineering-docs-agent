---
title: Decision Archive
status: draft
---

# Decision Archive

_Decision Archive: ADRs, design rationale, and "why we chose X" records._

<!-- docs-agent:overview:start -->
**In this section**

- **Orchestrator: two-stage subagent output parse pipeline** — PR #75 introduced a `_strip_code_fence` helper that sits in front of the existing `_rescue_json_object` path inside `dispatch_subagent`. Together they form a two-stage pipeline for turning raw subagent output into parsed JSON.
- **CCE-14: Source Collector Prompt Hardening** — CCE-14 investigated why source-collector output parsing failed in baseline runs. The investigation used stream-json diagnostics (built in CCE-12) to observe ground-truth tool-call sequences. It identified two root causes: `_extract_final_assistant_text` returning `""` when the model's final assistant turn contained only `tool_use` blocks, and a user-level plugin's `SessionStart` hook injecting "★ Insight" prose before the JSON output (addressed as CCE-15).
- **CCE-15: Source Collector Root Cause Sweep** — CCE-15 diagnosed two independent failure modes in the source-collector dispatch path that caused the orchestrator to silently misread subagent output. Both modes were confirmed in CCE-14 production runs. This page documents the root causes, the fixes, and the test coverage that pins each behavior.
- **CCE-5 through CCE-9: Batch Prep Roadmap** — This page covers the architectural groundwork delivered across Jira tickets CCE-5 through CCE-9. Together they establish the orchestrator's runtime reliability: validated config/state loading, a dry-run test harness, and a releasable v0.1.0 baseline that subsequent capabilities build on.
- **v0.1.1 Hardening** — v0.1.1 is a stabilization release. It tightens the contracts between pipeline stages, expands test coverage across the orchestrator and verification paths, and rounds out the Tier-1 lint rule set. No new capabilities are added; the focus is correctness under edge cases the initial release exposed.
- **Measurements archive** — _Auto-generated; 7 entries. Do not edit by hand — see `scripts/archive_indexes.py`._
- **Plans archive** — _Auto-generated; 54 entries. Do not edit by hand — see `scripts/archive_indexes.py`._
- **Specs archive** — _Auto-generated; 50 entries. Do not edit by hand — see `scripts/archive_indexes.py`._

_8 pages · regenerated nightly_
<!-- docs-agent:overview:end -->

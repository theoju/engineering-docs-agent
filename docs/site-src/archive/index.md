---
title: Decision Archive
status: draft
---

# Decision Archive

_Decision Archive: ADRs, design rationale, and "why we chose X" records._

<!-- docs-agent:overview:start -->
**In this section**

- **CCE-109 Doom Loop Resolution: Backlog Catch-Up Run (2026-06-10)** — Since 2026-05-29, the nightly docs-agent had been stuck in a doom loop. Each CI run re-processed the full ~35-PR backlog window, hit the 60-minute job timeout, and exited without advancing `last_successful_run`. The next run would pick up the same window and repeat the cycle.
- **Decision: CCE-99 — Post-Merge Branch Pruning Hook** — **Date:** 2026-06-10
- **Decision: Soft Time Budget for the Nightly Orchestrator Runner (CCE-109)** — **Date:** 2026-06-10
- **CCE-105: API Reference Grouping and JSON-Schema Contracts Extractor** — **Date:** 2026-06-09
- **Decision: Nav Overhaul — Generated Nav Block Replaces awesome-pages (2026-06-09)** — **Date:** 2026-06-09
- **Release Decision: v0.5.1 (2026-06-09)** — **PR:** #124
- **Decision: SDD Fidelity Verification Ladder (CCE-92)** — **Date:** 2026-06-08
- **Decision: Docs-Agent Cadence Invariant and Cron Pause (2026-06-05)** — **Date:** 2026-06-05
- **Decision: Freshest-Only Policy for docs-agent PRs (CCE-89 D2)** — **Date:** 2026-06-05
- **CCE-77 Ship Guardrails Fix — Decision Record** — **Date:** 2026-06-04
- **Decision: Docstring lint guard for bare CLI flag syntax (CCE-87)** — **Date:** 2026-06-04
- **Decision: Plan-step verification must use the actual consumer tool** — **Date:** 2026-06-04
- **Decision: SDD Fidelity Gate (2026-06-04)** — **Tickets:** CCE-92 (umbrella), CCE-93 (implementer / Tier 0), CCE-94 (reviewer gate), CCE-95 (upstream PR, pending)
- **Decision: Dry-Run Fixture Pattern for CCSA Onboarding Prep (CCE-57)** — **Date:** 2026-06-03
- **Orchestrator: two-stage subagent output parse pipeline** — PR #75 introduced a `_strip_code_fence` helper that sits in front of the existing `_rescue_json_object` path inside `dispatch_subagent`. Together they form a two-stage pipeline for turning raw subagent output into parsed JSON.
- **CCE-14: Source Collector Prompt Hardening** — CCE-14 investigated why source-collector output parsing failed in baseline runs. The investigation used stream-json diagnostics (built in CCE-12) to observe ground-truth tool-call sequences. It identified two root causes: `_extract_final_assistant_text` returning `""` when the model's final assistant turn contained only `tool_use` blocks, and a user-level plugin's `SessionStart` hook injecting "★ Insight" prose before the JSON output (addressed as CCE-15).
- **CCE-15: Source Collector Root Cause Sweep** — CCE-15 diagnosed two independent failure modes in the source-collector dispatch path that caused the orchestrator to silently misread subagent output. Both modes were confirmed in CCE-14 production runs. This page documents the root causes, the fixes, and the test coverage that pins each behavior.
- **CCE-5 through CCE-9: Batch Prep Roadmap** — This page covers the architectural groundwork delivered across Jira tickets CCE-5 through CCE-9. Together they establish the orchestrator's runtime reliability: validated config/state loading, a dry-run test harness, and a releasable v0.1.0 baseline that subsequent capabilities build on.
- **v0.1.1 Hardening** — v0.1.1 is a stabilization release. It tightens the contracts between pipeline stages, expands test coverage across the orchestrator and verification paths, and rounds out the Tier-1 lint rule set. No new capabilities are added; the focus is correctness under edge cases the initial release exposed.
- **ADR: Required Status Checks Must Not Carry a Workflow-Level `paths:` Filter** — **CCE-91 — 2026-06-09**
- **Auth-tier migration: drop explicit API key threading** — **PR #91 · merged 2026-06-09 · non-breaking**
- **Measurements archive** — _Auto-generated; 7 entries. Do not edit by hand — see `scripts/archive_indexes.py`._
- **Plans archive** — _Auto-generated; 60 entries. Do not edit by hand — see `scripts/archive_indexes.py`._
- **PR Summarizer — Design Decisions** — This page records the design rationale behind the `pr-summarizer` subagent (`agents/pr-summarizer.md`). It is an archive document: it explains *why* the agent is shaped the way it is, not *what it currently does*. For the current interface, see the agent definition directly.
- **Specs archive** — _Auto-generated; 56 entries. Do not edit by hand — see `scripts/archive_indexes.py`._

_25 pages · regenerated nightly_
<!-- docs-agent:overview:end -->

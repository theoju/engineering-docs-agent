---
title: Decision Archive
status: draft
---

# Decision Archive

_Decision Archive: ADRs, design rationale, and "why we chose X" records._

<!-- docs-agent:overview:start -->
**In this section**

- **A failed GitHub App-token mint degrades the run to partial, it never kills the job** — The nightly workflow's App-token step now runs under `continue-on-error`, and a mint failure is treated as a blocking-but-survivable signal that skips auto-merge instead of aborting the job outright.
- **CCE-127: App-token degradation — operational learnings** — This entry captures what shipping the CCE-127 fix actually took, beyond the mechanism itself. The mechanism (degrade to `partial` instead of failing the job) is documented in `CLAUDE.md` and in the spec at `docs/superpowers/specs/2026-08-07-cce127-app-token-degrade-partial-design.md`. What follows is the trap list every contributor should read before touching the GitHub App-token step or the workflow/orchestrator boundary again.
- **Advisory Agent Dispatch Failures Are Info-Only, Not Partial (2026-07-24)** — `gap-detector` and `fact-checker` are the two advisory subagents in the eight-agent pipeline. Their output only ever feeds a note on the docs-agent PR — `fact-checker` populates `fact_check_warnings`, `gap-detector` populates the "Gaps flagged" section — and neither feeds the CCE-101 auto-merge gate. The blocking pipeline is the other five: source-collector, pr-summarizer, page-author, content-validator, notifier. That distinction is now a named convention in CLAUDE.md, but it was learned the hard way, twice.
- **CCE-124 — archive-lens `citation_exists` advisory via per-result lint severity** — Ticket: CCE-124 · PR #191 · 2026-07-23
- **CCE-125: gap-detector `needs_spec: null` becomes a first-class "unjudged" value** — PR #189's nightly run came out `partial` for three reasons. Two were already fixed
- **Decision: Provider-Aware Publish Trigger (CCE-123)** — **Date:** 2026-07-24
- **Code citations go line-free; citation-location precision moves to a lint** — Docs used to cite code as `` `path:line` `` — e.g. `` `scripts/orchestrator_runner.py:1240` ``. Line numbers are the single most churn-sensitive part of a citation: any edit above the cited line shifts it, so an unrelated change turns a correct citation "stale." PR #179 (2026-07-16) surfaced eight fact-checker `contradiction` warnings that were all really this — benign line drift, not a real factual problem — and the CCE-101 auto-merge gate requires zero fact-checker warnings, so those warnings blocked auto-merge on docs that were otherwise correct.
- **Decision: CircleCI Provider Seam for the Publish-Verifier Is Modeled but Unvalidated (CCE-63)** — - **Ticket:** CCE-63 (parent CCE-58)
- **CCE-119: Create-Path Frontmatter Fidelity (2026-07-15)** — CCE-117 made the incremental authoring **create** path generator-aware: for an `agent-authored` section, the orchestrator deterministically synthesizes the required frontmatter (`description`, `source_files`, `last_reviewed`, `status`) so a new page clears Tier-1 lint instead of being dropped. That fix closed a recurring failure mode — 20 blocked architecture pages in one nightly run — but left two residuals, tracked as CCE-119 and split out of CCE-118.
- **CCE-120: Orchestrator-Injected `pr_id` for Gap-Detector Verdicts** — `agents/schemas/gap_detector.schema.json` marks `pr_id` as required. Nightly PR #173 (2026-07-12) went `partial` for exactly one reason: `schema_invalid: gap-detector: 'pr_id' is a required property`. That single reason was enough to block CCE-101 auto-merge, even though every other dispatch reason on that run was already `info_only`.
- **A benign JSON rescue no longer flips a run to `partial`** — Every nightly run that triggered a JSON rescue on a blocking-pipeline subagent
- **CCE-99: post-merge local branch prune hook** — Merged feature branches were lingering locally after `gh pr merge` because nothing pruned them. The 2026-06-04 sweep recovered 13 stale `[gone]` refs; a follow-up sweep on 2026-06-10 recovered 7 more. CCE-90 had already shipped an in-repo floor (`scripts/prune_merged_branches.py`), but that only helps when an operator remembers to run it, and only inside this repo.
- **Decision: Publish-Verifier Run Selection Is Event-Agnostic (CCE-115)** — The `publish-verifier` subagent's step 1 no longer filters build-workflow runs by trigger event. It now selects the newest `build_workflow` run whose `createdAt` is at or after the merge time, whatever fired it, then polls that run until `status=completed` and maps its `conclusion` to `build_status`.
- **CCE-109 Doom Loop Resolution: Backlog Catch-Up Run (2026-06-10)** — Since 2026-05-29, the nightly docs-agent had been stuck in a doom loop. Each CI run re-processed the full ~35-PR backlog window, hit the 60-minute job timeout, and exited without advancing `last_successful_run`. The next run would pick up the same window and repeat the cycle.
- **CCE-114: the authoring fan-out ignored the CCE-109 time budget** — CCE-109's soft deadline only gated PR admission; the page-author fan-out ran unbounded past it, and six nightlies died at the workflow's 60-minute hard kill.
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
- **Nightly partial-run banner now matches the actual `partial` flag** — PR #177 fixes a display bug: a clean, auto-merge-eligible nightly run could still
- **Plans archive** — _Auto-generated; 70 entries. Do not edit by hand — see `scripts/archive_indexes.py`._
- **PR Summarizer — Design Decisions** — This page records the design rationale behind the `pr-summarizer` subagent (`agents/pr-summarizer.md`). It is an archive document: it explains *why* the agent is shaped the way it is, not *what it currently does*. For the current interface, see the agent definition directly.
- **Specs archive** — _Auto-generated; 67 entries. Do not edit by hand — see `scripts/archive_indexes.py`._

_39 pages · regenerated nightly_
<!-- docs-agent:overview:end -->

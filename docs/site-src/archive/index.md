---
title: Decision Archive
status: draft
---

# Decision Archive

_Decision Archive: ADRs, design rationale, and "why we chose X" records._

<!-- docs-agent:overview:start -->
**In this section**

- **CCE-127 app-token degradation: learnings** — PR #195 shipped the CCE-127 fix: a failed GitHub App-token mint now degrades
- **CCE-127 — a failed App-token mint degrades the run to partial instead of killing the job** — A failed GitHub App installation-token mint no longer aborts the nightly job. It now falls back to `secrets.GITHUB_TOKEN`, finishes the run, and records a blocking `app_token_unavailable` reason that flips the run to `partial` — which disables auto-merge through the existing CCE-101 interlock.
- **CCE-123: provider-aware publish trigger** — The post-merge publish pipeline had two GitHub-only seams. CCE-63 fixed the
- **CCE-124: archive-lens `citation_exists` advisory via per-result lint severity** — `citation_exists` is a Tier-1 block rule: every inline-code span in a page's
- **CCE-125: `gap-detector`'s `needs_spec: null` becomes a first-class "unjudged" value** — **Ticket:** CCE-125 · **Date:** 2026-07-23 · **PR:** #192
- **Decision: Advisory Agents Never Flip a Run to `partial` (2026-07-24)** — Nightly PR #189 went `partial` for a single reason: `gap-detector`'s documented malformed-input fallback, `{"error": "malformed_input", "needs_spec": null}`, failed its own schema — `needs_spec` was declared a required non-nullable boolean, so `validate_and_parse` returned `schema_invalid`. The dispatch callsite recorded that as a failure via `_record_dispatch_reasons(ok=False)`, and the run flipped `partial`, blocking the CCE-101 auto-merge gate.
- **CCE-122: Stable, line-free code citations** — Docs prose used to cite code as `` `path:line` `` (e.g.
- **CCE-63: a CircleCI provider seam for the publish-verifier** — The publish-verifier step (the post-merge check that confirms a docs-agent PR actually went live) only ever knew one CI: GitHub Actions. `publishing.ci_provider: circleci` had existed as a schema enum value since CCE-58, but nothing consumed it — a host could set it and nothing would happen differently. CCE-63 (PR #188) is the deferred consumer, and the decision worth recording here is less "what got built" and more "why it stops short of a real CircleCI poller."
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

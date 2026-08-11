---
title: Decision Archive
status: draft
---

# Decision Archive

_Decision Archive: ADRs, design rationale, and "why we chose X" records._

<!-- docs-agent:overview:start -->
**In this section**

- **CCE-138: Authoring-Loop Truncation Silently Advanced the Baseline to Full Window HEAD** — An authoring-truncated nightly run persisted a baseline claiming coverage of the whole review window even when it had written only one of several page batches — because the authoring loop's time-budget break never set the flag the promotion block needed to route it onto the safe path.
- **CCE-139: citation source roots — widening `citation_exists` for nested monorepos** — - **Status:** landed (PR #212)
- **CCE-134: Citation Exempt Token, Not Example Prefix** — Nightly run 31275900434 went `partial`. `citation_exists` (Tier-1, block)
- **CCE-127: A Failed App-Token Mint Degrades the Nightly to `partial`, It No Longer Kills the Job** — The dogfood nightly in `theoju/engineering-docs-agent` failed 15 nights running, from
- **CCE-130: Stale Branch Archive and Prune (2026-08-08)** — **PR:** #199
- **CCE-131 — `citation_exists` false-positive closure** — `citation_exists` is a Tier-1 **block** rule: when it fails a page, the
- **Postmortem: GitHub App-token failures silently killed 15 nightlies (CCE-127)** — From 2026-07-23 to 2026-08-07, the nightly docs-agent run failed 15 consecutive nights on both `theoju/engineering-docs-agent` and `theoju/claude-code-self-assessment` — roughly 30 failed runs total. Nobody noticed for two weeks because neither repo had `SLACK_WEBHOOK_URL` wired; the dogfood repo now carries it so this class of outage pages a human.
- **Advisory agents never flip a run to `partial`** — `gap-detector` and `fact-checker` are advisory agents. A dispatch failure on either one is recorded info-only — it never flips a nightly run to `partial`. That gate belongs solely to the blocking pipeline: source-collector, pr-summarizer, page-author, content-validator, and notifier. Only those five flip `partial` on failure, via `_record_dispatch_reasons(state, reasons, ok=<dispatch produced usable output>)`.
- **Archive-lens citations are advisory, not blocking** — `citation_exists` (Tier-1, normally `block`) now emits **per-result** severity
- **CCE-123: Publish-Trigger Provider-Aware Dispatch (2026-07-24)** — CCE-63 made the post-merge **verify** seam provider-aware: `scripts/verify_runner.py` forks on `publishing.ci_provider`, and a non-github provider degrades honestly through `build_poller.resolve_build_verdict` — a non-promoting verdict plus a fixed `circleci_provider_modeled_but_unvalidated` reason — instead of mis-verifying a build it can't actually see. That work deliberately left a second GitHub-only seam open: the post-merge **trigger**.
- **CCE-125: gap-detector `needs_spec: null` Becomes a First-Class "Unjudged" Value (2026-07-23)** — Nightly PR #189 came out `partial` for three reasons. Two were already understood: `citation_exists` lint_block was fixed by CCE-124, and `prose_contamination_rescued: fact-checker` had already been info-only since CCE-118. The third was the sole remaining driver: `schema_invalid: gap-detector: None is not of type 'boolean'`.
- **CCE-122: stable code citations — line-free, split across a lint and the fact-checker** — Docs prose used to cite code as `` `path:line` ``. Line numbers are the single
- **Decision: CircleCI Provider Seam for the Publish-Verifier (CCE-63)** — - **Ticket:** CCE-63 (parent: CCE-58, `advanced-data-import-system` onboarding)
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
- **Plans archive** — _Auto-generated; 74 entries. Do not edit by hand — see `scripts/archive_indexes.py`._
- **PR Summarizer — Design Decisions** — This page records the design rationale behind the `pr-summarizer` subagent (`agents/pr-summarizer.md`). It is an archive document: it explains *why* the agent is shaped the way it is, not *what it currently does*. For the current interface, see the agent definition directly.
- **Specs archive** — _Auto-generated; 68 entries. Do not edit by hand — see `scripts/archive_indexes.py`._

_44 pages · regenerated nightly_
<!-- docs-agent:overview:end -->

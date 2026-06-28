---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# CCE-114: Time-budget enforcement in the page-author fan-out

**Date:** 2026-06-10  
**PR:** [#136](https://github.com/theoju/engineering-docs-agent/pull/136)  
**Ticket:** CCE-114

## Context

CCE-109 introduced a per-run soft deadline to keep nightly docs runs inside the 60-minute GitHub Actions wall clock. The implementation wired the deadline check to two places: PR admission (early in the run) and the CCE-101 auto-merge gate (late in the run). Nothing checked the deadline inside the three expensive subagent loops — page-author fan-out, fact-checker, and gap-detector.

## Problem

The page-author fan-out is the most expensive section of a run. A backlog window routinely produces 43–50 Opus dispatches. Without a deadline check inside the loop, those dispatches ran unconditionally regardless of elapsed time.

Six consecutive nightly runs were killed at the GitHub Actions 60-minute limit after CCE-109 shipped. Run `27263616736` (2026-06-10 08:30 UTC) is the canonical incident: it started roughly 20 page-author dispatches after its own 45-minute deadline, was cancelled mid-loop by the job kill, and discarded an hour of accumulated work. `state.json.last_successful_run` stalled — the next run re-processed the same window from scratch.

The root cause: CCE-109 threaded the deadline through the orchestrator's outer control flow but left the fan-out loop itself unconstrained.

## Decision

CCE-114 (PR #136) inserted deadline checks into all three subagent loops.

**Page-author fan-out.** The orchestrator checks the soft deadline before dispatching each batch. If the deadline has passed, remaining batches are skipped and the run proceeds to the next stage. An **at-least-one-progress guarantee** applies: even when the deadline is already expired at the moment the fan-out starts, the orchestrator dispatches one batch before halting. This keeps tight budgets crawling forward rather than producing a zero-progress run.

**Fact-checker.** When the budget is expired at the start of the fact-checker stage, the orchestrator skips all fact-checker dispatches outright and flips `partial: true` on the run. A page that was never fact-checked blocks the CCE-101 auto-merge gate, the same as a page where the fact-checker found warnings.

**Gap-detector.** Applies the same skip-and-partial posture. An expired budget causes the gap-detector loop to exit immediately; affected PRs are not flagged as well-covered — they are simply not checked.

## Consequences

A run cut short by the deadline produces a `partial: true` PR. The PR is still opened, still contains the pages that were authored, and still identifies which pages were skipped.

- Merging the partial PR accepts the authored pages and acknowledges the coverage gap for that window.
- Not merging leaves the PR open. The next nightly run starts from the same `last_successful_run` head SHA and retries the full window with a fresh budget.

`state.json.last_successful_run` advances only on merge, so an unmerged partial PR does not silently drop changes from the window.

The new test file `tests/orchestrator/test_time_budget_authoring.py` drives the real `run()` with a fake monotonic clock and covers four scenarios: full budget (no skips), expired budget before fan-out start (at-least-one fires), expired budget mid-fan-out, and expired budget before fact-checker. The full suite passed at 1063 tests, 3 skipped.

## See also

- `docs/site-src/architecture/orchestrator.md` — reference description of the time-budget enforcement model.
- `docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md` — the merge-gate design that the `partial` flag feeds into.

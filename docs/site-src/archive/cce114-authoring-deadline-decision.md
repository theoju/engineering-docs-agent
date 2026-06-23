---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# CCE-114: Authoring Deadline Enforcement — Decision Record

**Date:** 2026-06-11
**Ticket:** CCE-114
**PR:** [#136](https://github.com/theoju/engineering-docs-agent/pull/136)
**Status:** Shipped

## Context

CCE-109 introduced a soft wall-clock deadline (`budget_seconds`) for nightly runs. The check fired once — at PR admission, early in the pipeline — and then the run proceeded unchecked through all subsequent phases.

The page-author fan-out is the most expensive phase. A large unprocessed backlog window dispatches up to ~50 Opus subagent calls in sequence. Six consecutive scheduled nightly runs (2026-06-05 through 2026-06-10) were killed at the GitHub Actions `timeout-minutes: 60` limit during this phase. Run 27263616736 had 43 dispatches in flight when the job died.

Each killed run discarded all its work: no PR was opened, `state.json.last_successful_run` was not advanced, and the backlog window grew. The next run inherited the same oversized window and hit the same limit. The system was in a self-reinforcing doom loop.

## The gap

The CCE-109 deadline was checked between PR admissions (early) but never inside the authoring loop. The fact-checker loop and gap-detector loop had no deadline awareness at all. Once the page-author fan-out started, it ran to completion — or until the job runner killed it.

## Decision

Add a deadline check **before each authoring batch** inside the page-author fan-out loop.

Use an at-least-one-progress guarantee: even if the deadline is already expired at loop entry, dispatch at least one batch so the run always crawls forward. A zero-progress run would not advance `state.json.last_successful_run` and would replicate the doom loop.

**On deadline expiry, flip the PR to `partial: true`** in the body rather than silently dropping the unprocessed pages. The `partial` flag blocks CCE-101 auto-merge, leaving the PR open for operator review. This makes the operational gap visible — a partial docs update is preferable to no update and no signal.

**Skip the fact-checker loop outright** once the deadline expires after authoring. Running partial fact-checking on a subset of authored pages would produce misleading signal; skip entirely and note the expiry in the PR body.

**Skip the gap-detector loop** on expiry under the same posture. Gap detection against an incomplete authoring pass produces noise, not insight.

## Alternatives considered

**Kill the run with a hard error on deadline breach.** Rejected. A hard error prevents `state.json.last_successful_run` from advancing and re-enters the doom loop.

**Run authoring in parallel to fit within the budget.** Deferred. Parallel Opus dispatches complicate the partial-progress model and require a separate concurrency budget design. The serial-with-deadline model solves the immediate safety problem.

**Raise `timeout-minutes`.** Rejected as the only fix. The underlying issue is unbounded fan-out, not an insufficiently generous timeout. Raising the limit delays the failure; the deadline model bounds it.

## Outcome

The three enforcement points shipped in `scripts/orchestrator_runner.py` (+41/-−4 lines):

1. **Authoring batch gate** — deadline check before each batch; at-least-one-progress guarantee on first iteration.
2. **Fact-checker skip** — loop exits immediately if deadline is expired on entry.
3. **Gap-detector skip** — loop exits immediately if deadline is expired on entry.

Both skip paths set `partial: true` on the PR. The nightly baseline (`state.json.last_successful_run`) advances on any partial run that opens a PR, ending the doom loop.

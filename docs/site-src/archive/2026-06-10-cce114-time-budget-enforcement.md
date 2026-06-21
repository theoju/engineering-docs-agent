---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# Decision: Time-Budget Enforcement Inside the Fan-Out Loops (CCE-114)

**Date:** 2026-06-10  
**PR:** [#136](https://github.com/theoju/engineering-docs-agent/pull/136)  
**Tickets:** CCE-114 (closes the CCE-109 enforcement gap)

## Problem

CCE-109 introduced a soft time budget (default 2700 s) and checked it at PR admission and at the merge gate. That left the three fan-out loops — page-author, fact-checker, and gap-detector — completely unguarded. Those loops account for roughly 85 % of total dispatch time; up to ~50 Opus dispatches can fire in a single backlog window.

Six consecutive nightly runs were killed by the GitHub Actions 60-minute hard limit. Run 27263616736 (2026-06-10) is the most recent documented case. Each kill had two compounding effects:

1. An hour of completed work was discarded because the runner never reached the commit step.
2. `state.json.last_successful_run` was not advanced, so the next night's run inherited the same window plus one additional day of PRs.

The result was a self-reinforcing doom loop identical to the one CCE-109 was designed to prevent — except the doom loop lived entirely inside the fan-out, not at admission.

## Decision

Enforce the CCE-109 soft deadline at the entry of every authoring batch, and apply a fail-fast posture to fact-checking and gap-detection once the deadline is past.

**At-least-one-progress guarantee.** If the deadline has already expired when the page-author fan-out starts, the runner still processes one batch before truncating. This mirrors the CCE-109 PR-admission invariant: zero forward progress per run is never acceptable.

**Fact-checker: skip on expiry.** When the deadline is expired before the fact-checker loop starts, the loop is skipped entirely and the run is marked `partial: true`. A partial run is ineligible for auto-merge under CCE-101, so a half-checked PR cannot reach production without operator review.

**Gap-detector: skip on expiry.** Same posture. Gap flags are advisory-only, so skipping them on a tight budget has no correctness cost.

## Root cause

CCE-109 introduced `time_budget_seconds` and wired it at two points: PR admission (cheapest) and the auto-merge check-wait (bounded). It did not wire it inside the fan-out because the fan-out was a single loop at that time. As the loop was split into three distinct phases — author, fact-check, gap-detect — each new phase inherited no budget awareness.

The enforcement gap was invisible until the backlog grew large enough that admission-time checks passed (the window still fit, in theory) while the actual dispatch work overran the wall clock.

## Design

The deadline check before each authoring batch uses the same `_budget_remaining()` helper introduced by CCE-109. No new timing infrastructure is required.

The at-least-one-progress guarantee is implemented as a `processed_count` gate: skip the deadline check for the first batch; apply it to all subsequent batches. This is the same pattern used at PR admission.

When the fact-checker loop is skipped, the runner sets `partial: true` on `current_run` before writing `state.json`. The auto-merge gate in `_maybe_auto_merge()` already refuses partial runs — no new gate logic is needed.

Gap-detector skip uses the same `partial: true` flip. There is no separate gap-detection result that could be silently omitted; the skipped state is explicit in the run record.

## Test coverage

Four new TDD tests cover the behavioral contract:

| Test | Assertion |
|---|---|
| Authoring truncation | Fan-out stops mid-batch when the deadline expires; already-authored pages are committed; `partial: true` |
| Fact-checker skip | When deadline is expired at fact-check start, no fact-checker dispatches fire; `partial: true` |
| Gap-detector skip | When deadline is expired at gap-detect start, no gap-detector dispatches fire; `partial: true` |
| Unlimited budget passthrough | With `time_budget_seconds: 0`, all three phases run to completion regardless of elapsed time |

All tests use the fixture-driven dry-run path. No production Claude CLI dispatch occurs.

## Relationship to CCE-109

CCE-109 is the parent design; CCE-114 closes its enforcement gap. The config key (`run.time_budget_seconds`), the `partial` semantics, the at-least-one-progress invariant, and the auto-merge eligibility check are all unchanged. CCE-114 adds no new config surface.

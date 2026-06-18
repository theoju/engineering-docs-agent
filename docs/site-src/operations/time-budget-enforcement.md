---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
---

# Time Budget Enforcement

The nightly runner enforces a soft deadline (CCE-109) to prevent the 60-minute GitHub Actions job timeout from killing a run with all work discarded. This page explains where the deadline is checked, what happens when it fires, and what you see in partial runs.

## Background

The CCE-109 budget was originally checked only at two points: between PR admissions and at the CCE-101 auto-merge gate. The page-author fan-out phase — the most expensive phase — was completely unbounded.

In practice this meant: if a run started late or a PR window was large, the runner dispatched every page-author subagent regardless of how much time remained. Six consecutive nightly runs (June 5–10, 2026) were killed by the Actions 60-minute hard wall. Run 27263616736 dispatched 43 page-author subagents for a 7-PR window; roughly 20 of them started after the 09:15:39 soft deadline. Each cancelled run burned approximately one hour of Opus dispatches with all work discarded, no PR produced, and no state advance — a doom loop.

## Where the deadline is now checked

The fix (PR #136) inserts a deadline check at three points inside the fan-out phase:

1. **Before each doc-target authoring dispatch.** Before the runner dispatches a page-author subagent for a given target, it compares `time.monotonic()` against the CCE-109 soft deadline. If the deadline has passed, the target is skipped.
2. **Inside the per-page fact-checker loop.** Each fact-check iteration re-consults the deadline before dispatching.
3. **Inside the per-PR gap-detector loop.** Same pattern: each gap-detector dispatch is gated on remaining budget.

The deadline is a _soft_ limit. The runner does not abort mid-dispatch; it defers targets that have not started yet.

## What `time_budget_exceeded` means

When the deadline fires mid-fan-out, deferred targets are recorded with the partial reason `time_budget_exceeded`. The run is marked `partial: true` in the PR body.

The PR is still opened. Lint and PR-open tail work run on whatever pages were authored before the deadline. The `state.json` `last_successful_run` does **not** advance on a partial run; the deferred targets are picked up in the next nightly window.

If you see `partial: true` + `time_budget_exceeded` in a PR body, the run ran out of budget before all targets were authored. The pages that were completed are still correct and land normally. No authored content is discarded.

## What triggers a partial run

A partial run from budget exhaustion is most likely when:

- The PR window is large (many merged PRs with many doc targets).
- The runner was queued and started late in the Actions slot.
- A prior phase (PR summarization, voice-load) ran longer than expected.

Reduce the window size by merging docs-agent PRs promptly. The CCE-101 auto-merge gate does this automatically for eligible runs.

## Test coverage

41 tests covering the new budget-enforcement paths were added alongside the implementation. They exercise deadline expiry at each of the three insertion points, verify that tail work (lint, PR-open) still runs after a budget-triggered deferral, and confirm that non-exhausted runs are unaffected.

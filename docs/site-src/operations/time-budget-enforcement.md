---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: architecture
---

# Time Budget Enforcement

The nightly orchestrator runs inside a 60-minute GitHub Actions hard timeout. The CCE-109 soft deadline keeps the runner well inside that limit by stopping new work early — before the hard limit fires — so that at least partial results land in a PR and `state.json` advances.

## The Problem

Before PR #136 (CCE-114), the soft deadline was checked in only two places: between PR admission decisions and at the auto-merge gate. The page-author fan-out — the most expensive phase of every run — was unchecked.

On a large change window (~43 doc targets), roughly 20 page-author dispatches would start after the soft deadline had already passed. Each dispatch still ran to completion, burning Opus API time. When the GitHub Actions hard limit finally fired, the runner exited, all in-flight work was discarded, and `state.json` never advanced. The next nightly run would re-discover the same change window and repeat the failure identically — a compounding doom loop.

Six consecutive scheduled runs (June 5–10, 2026) hit this loop. Run 27263616736 is the forensic anchor: it shows 20 of 43 page-author dispatches starting after the 09:15 UTC soft deadline.

## Where the Checks Are Inserted

The orchestrator now checks the soft deadline at three additional points inside the authoring phase:

**Before each page-author dispatch.** If the deadline has passed, the orchestrator stops dispatching immediately, marks all remaining targets as `partial_reason: time_budget_exceeded`, and moves to the lint stage.

**Inside the per-page fact-checker loop.** A pre-call deadline check guards each fact-checker invocation. A slow fact-check on one page cannot push the next dispatch past the budget.

**Inside the per-page gap-detector loop.** Same guard as the fact-checker — the pattern is consistent across both post-authoring passes.

## What Happens When the Budget Is Exceeded

The orchestrator does not abort the run. It drains the current in-flight dispatch, then skips remaining targets. It proceeds to lint and opens a PR for whichever targets completed.

The PR body reflects `partial: true` so the gap is visible rather than silent. Per spec §8, a partial run still produces a PR — an operational gap should never be silent.

## Interaction with the Auto-Merge Gate

The auto-merge gate (CCE-101) refuses to auto-merge a partial run. A PR carrying `partial: true` is left open for operator review; the auto-merge stage records `skip_reason: partial_run` in the run log and moves on without error.

`state.json.last_successful_run` advances only when the PR merges — auto or manual. A partially-completed run does not suppress the next run's change window. Deferred targets re-appear the following night.

## Budget Constants

Two time constants from CCE-109 are consumed from the same wall-clock budget as the authoring phase:

| Constant | Value | Purpose |
|---|---|---|
| Grace period for checks to register | 120 s | Allows GitHub to record CI checks before the runner polls |
| Max wait for checks to settle | 900 s | Upper bound on polling at the auto-merge gate |

The soft deadline itself is derived from the job start time and the `time_budget_seconds` value in the host's `.engineering-docs-agent/config.yml`.

## Operator Signals

When enforcement fires, the run log emits:

```
[orchestrator] time budget exceeded; deferring N remaining targets (partial_reason=time_budget_exceeded)
```

The docs-agent PR body lists deferred targets under a **Partial Run** section. Completed targets appear in the PR normally; deferred targets do not.

If you see repeated partial runs with a large deferred count, the practical remedies are:

- **Merge more frequently.** A smaller change window means fewer targets per night. This is the most reliable fix.
- **Increase `time_budget_seconds`.** Set a higher value in `.engineering-docs-agent/config.yml`, leaving a safety margin below the Actions job timeout (currently 60 minutes for hosted runners).
- **Narrow `docs.agent_editable_paths`.** Fewer editable paths → fewer doc targets discovered per run.

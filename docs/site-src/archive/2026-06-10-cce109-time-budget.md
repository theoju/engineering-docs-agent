---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/128
synthesized_into: []
doc_kind: decision
---

# Decision: Soft Time Budget for the Nightly Orchestrator Runner (CCE-109)

**Date:** 2026-06-10  
**PR:** [#128](https://github.com/theoju/engineering-docs-agent/pull/128)  
**Tickets:** CCE-109

## Problem

When the processing window grew large enough to exceed the 60-minute CI job wall limit, the runner was killed mid-run. Because it had not finished, it could not advance `last_successful_run.head_sha`. The next nightly run inherited the same window — now with an additional day's PRs appended — and was killed again. Each kill enlarged the window for the next attempt.

This was a self-reinforcing doom loop. No progress was ever committed, and the window grew without bound.

## Decision

Add a soft time budget to the orchestrator runner. The default is 2700 s (45 min), leaving a safety margin inside the 60-minute CI limit. When the budget is exhausted, the runner truncates processing, marks the run partial, and advances the state cursor to the last fully-processed PR's merge SHA. The next run drains the remainder.

The invariant is: **at least one PR is fully processed before any truncation.** The doom loop required zero progress per run; this guarantees a positive lower bound.

## Alternatives considered

**Hard kill with no cursor advance (status quo):** Eliminated. Zero progress per run is the root cause.

**Splitting the window into fixed-size batches at run start:** Considered but discarded. Batch size would need to be tuned per host and does not adapt to variable per-PR processing cost.

**Raising the CI job timeout:** Treats the symptom, not the cause. A sufficiently large backlog still hits any fixed limit, and CI platform limits vary by host.

**Async / background processing:** Out of scope for a nightly GitHub Actions workflow. The runner is synchronous by design.

## Design

The budget is configurable in `.engineering-docs-agent/config.yml`:

```yaml
run:
  time_budget_seconds: 2700   # default; 0 disables the budget entirely
```

You can also pass `--time-budget-seconds <n>` on the command line. Pass `0` to restore unlimited behavior.

PRs are sorted oldest-first before budget checks run. The runner admits PRs until the remaining budget would be exhausted, then stops. Oldest-first ordering ensures the state cursor advances monotonically and that a long-running backlog drains from the front, not arbitrarily.

When the run truncates, the orchestrator writes the merge SHA of the last fully-processed PR as the new `head_sha`. A Component-4 invariant guard validates two conditions before writing:

1. The new cursor is reachable from HEAD.
2. The new cursor is strictly forward of the prior baseline.

If either check fails, the write is refused with a reason code. The prior baseline is preserved and the same window retries on the next run.

## Relationship to existing invariants

**CCE-62 state-advancement invariant:** Preserved. The cursor only advances to a SHA that was fully processed, and the guard enforces forward-only movement.

**CCE-43 same-hour rerun guard:** The grace periods for CI check polling (120 s to register, 900 s to settle) are now bounded by the remaining run budget. The guard itself is hardened to failure-open: a missing or unreadable `state.json` defaults to allow rather than blocking the run.

**Partial-run semantics (spec §8):** Unchanged. A truncated run opens a docs-agent PR with `partial: true` in the body. The auto-merge gate rejects partial PRs; they require operator review.

## Edge cases patched in the same change

Five defects surfaced during the CCE-109 design review were fixed alongside the budget mechanism:

| Defect | Fix |
|---|---|
| First-run truncation used wall-clock order, not merge-time order | Oldest-first ordering applied before budget checks on first run |
| PRs without a merge SHA (deferred / not-yet-fully-merged) were silently dropped | Deferred PRs queued to the next run rather than lost |
| Abbreviated SHAs from the GitHub API did not match full-length stored SHAs | SHA comparison normalizes to full 40-char form before comparing |
| Same-hour guard threw on a missing `state.json` and blocked the run | Guard catches read errors and defaults to allow |
| PR body reported the full original window even when the run was truncated | Body reflects only the window actually processed |

## Schema changes

The config schema adds `run.time_budget_seconds` with an explicit note that `0` means unlimited.

The state schema adds two fields to the run record:

- `partial` — boolean; `true` when the run was truncated by the budget.
- `last_truncated_sha` — the merge SHA of the last PR that was cut from the current window, for diagnostics.

## Test coverage

19 new tests cover all plan behaviors and the five review-identified defects. They use the fixture-driven dry-run path; no production Claude CLI dispatch occurs.

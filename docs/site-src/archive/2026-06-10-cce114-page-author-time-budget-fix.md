---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# Decision: Extend the CCE-109 Time Budget Into the Page-Author Fan-Out (CCE-114)

**Date:** 2026-06-10  
**PR:** [#136](https://github.com/theoju/engineering-docs-agent/pull/136)  
**Tickets:** CCE-114 (root-cause fix; references CCE-109 and CCE-101 for context — neither ticket is reopened by this change)

## Problem

CCE-109 added a soft time budget to the nightly runner, but it only checked the deadline between PR *admissions* — the loop that decides which merged PRs enter the current run's window. Admission completes minutes into a run. The page-author fan-out that follows — one Claude dispatch per doc-target batch, and the most expensive phase of the pipeline — never checked the deadline at all. It ran unbounded until the workflow's hard `timeout-minutes: 60` GitHub Actions kill kicked in.

Six consecutive scheduled nightlies (2026-06-05 through 2026-06-10) hit this. Each one ran past the soft deadline, was killed by the hard limit, and discarded an hour of Opus dispatches with no PR opened and no baseline advance — the exact doom loop CCE-109 was written to close. Root-cause forensics (artifact `docs-agent-subagent-forensics-27263616736-1`) showed roughly 20 page-author dispatches starting *after* the computed deadline in a single run (27263616736).

## Decision

Check the soft deadline inside three loops that CCE-109 left unguarded, not just at admission:

1. **Page-author fan-out.** Before dispatching each doc-target batch, check the deadline. The first batch is unconditional — this preserves the CCE-109 at-least-one-progress guarantee so even a very tight budget authors at least one page batch before truncating. Every subsequent batch gates on the deadline.
2. **Fact-checker loop.** Before each advisory fact-checker dispatch, check the deadline. Once it has passed, skip the rest of the loop outright rather than gating per-item.
3. **Gap-detector loop.** Same pattern as the fact-checker loop: check once, skip the remainder outright once the deadline has passed.

Both advisory-loop skips explicitly set `partial=true`. This is the operative fix: without it, a page authored under budget but never fact-checked (because the fact-checker loop was skipped) would look identical to a normal warn-only pass and could clear the CCE-101 auto-merge gate. Flipping `partial` routes the run to `partial_reasons` and to the CCE-101 eligibility check, which rejects any partial run.

All three truncation paths preserve the CCE-109 invariant that a cut run still opens a PR (with `partial: true`) rather than discarding the work — the same behavior CCE-109 established for the admission loop, now extended to the phase that actually burns the clock.

## Observed behavior (test-pinned)

`tests/orchestrator/test_time_budget_authoring.py` pins the exact `partial_reasons` strings each loop emits, using a fixture that forces three doc-targets (`alpha`, `beta`, `gamma`) into three separate authoring batches:

| Scenario | Deadline trips at | Result |
|---|---|---|
| Authoring loop truncates | Batch 1 of 3 | `partial_reasons` contains `time_budget_exceeded: authored 1/3 page batches`; only `alpha.md` is written, `beta.md`/`gamma.md` never created |
| Fact-checker loop skips | After all 3 pages authored, before fact-check | `time_budget_exceeded: fact-checked 0/3 pages`; all 3 pages exist on disk — authoring itself was not cut |
| Gap-detector loop skips | After fact-checking completes, before gap detection | `time_budget_exceeded: gap-checked 0/3 PRs`; no fact-checker reason appears in `partial_reasons`, confirming the fact-checker loop finished cleanly before gap detection was the one to trip |
| Unlimited budget (`time_budget_seconds=0`) | Never | `partial` is `False`, no `time_budget_exceeded` reason, all 3 pages exist |

The per-loop gating means a run can go partial at any one of the three points independently — a tight budget that allows full authoring but not fact-checking still marks the run partial, because unreviewed pages must never look identical to reviewed ones for auto-merge purposes.

## Relationship to existing invariants

**CCE-109 soft time budget:** Extended, not replaced. The deadline computation and the `time_budget_seconds` config/CLI surface are unchanged; CCE-114 adds check points, it does not change how the deadline is computed or configured.

**CCE-101 auto-merge gate:** Directly protected by this fix. The gate's eligibility check already rejected `partial == true` runs; CCE-114 closes the gap where a run could finish non-partial despite skipping fact-checking, which would have let an unreviewed page slip through auto-merge.

**Partial-run semantics (spec §8):** Unchanged. A truncated or skip-affected run still opens (or appends to) a docs-agent PR with `partial: true` in the body, for operator review.

## Test coverage

Four new tests in `tests/orchestrator/test_time_budget_authoring.py` cover the authoring-loop truncation, the fact-checker-loop skip, the gap-detector-loop skip, and the unlimited-budget control case. All four use the fixture-driven dry-run path (`dry_run_dir`); no production Claude CLI dispatch occurs. Each test drives a scripted `now_monotonic` clock so the deadline trip point is deterministic rather than wall-clock-dependent.

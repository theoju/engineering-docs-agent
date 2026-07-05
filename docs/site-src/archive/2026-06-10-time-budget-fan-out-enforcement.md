---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# Time-budget enforcement in the post-admission fan-out loops (CCE-114)

## The incident

Six consecutive scheduled nightlies — June 5 through June 10 — died at the
workflow's hard `timeout-minutes: 60` kill. Each one discarded roughly an
hour of Opus dispatch work: no PR opened, no `state.json` advance, nothing
to show for the run.

Forensics on run `27263616736` found the cause: of 43 page-author
dispatches in that run, about 20 started **after** the CCE-109 soft
deadline had already passed.

## Why the CCE-109 deadline didn't catch it

CCE-109 added a soft time budget (`resolve_time_budget`,
`scripts/orchestrator_runner.py:339`), and the PR-admission loop already
checked it before each PR (`scripts/orchestrator_runner.py:1394`). But
admission is cheap and finishes minutes into a run — every PR in the
window is typically admitted well before the deadline. The expensive
phase comes after: the page-author fan-out, at up to ~50 dispatches per
window, ran with no deadline check at all. It just kept going straight
through the budget and into the workflow's 60-minute wall clock.

The advisory loops downstream of authoring — fact-checker and
gap-detector — had the same gap.

## The fix

The deadline is now checked inside each of the three post-admission
loops, not just at admission:

- **Page-author fan-out** (`scripts/orchestrator_runner.py:1474`): before
  each doc-target batch dispatch, if `deadline is not None and i > 0 and
  clock() > deadline`, the loop records a `time_budget_exceeded: authored
  N/M page batches` partial reason and stops. The `i > 0` guard mirrors
  admission's at-least-one-batch-makes-progress guarantee — the run
  never authors zero pages just because the clock ticked over between
  the deadline check and the first dispatch.
- **Fact-checker loop** (`scripts/orchestrator_runner.py:1671`): checked
  before every page, with no `i > 0` exemption. This loop is pure
  advisory overhead once the deadline has passed — every extra second
  spent here is a second closer to the hard kill — so it skips outright
  rather than guaranteeing one more page. The reason
  (`time_budget_exceeded: fact-checked N/M pages`) is **not**
  `info_only`: an authored page that was never fact-checked must not
  clear the CCE-101 auto-merge gate, and that gate keys off `partial`.
- **Gap-detector loop** (`scripts/orchestrator_runner.py:1786`): same
  skip-outright posture, same non-`info_only` reason
  (`time_budget_exceeded: gap-checked N/M PRs`).

In every case the PR is left open rather than silently dropped — the
operator can accept the coverage loss for that night or re-run inside a
wider window.

## What this doesn't change

An unlimited budget (`time_budget_seconds: 0` or CLI override) still
disables all three guards — `deadline` is `None` and every `clock() >
deadline` check short-circuits to false. Nothing about batching, the
per-batch dispatch shape, or the fact-checker's citation-gated dispatch
condition changed; only the deadline check was added around them.

## Verification

`tests/orchestrator/test_time_budget_authoring.py` pins all four cases
with a scripted fake clock: truncation mid-authoring
(`test_authoring_loop_truncates_after_budget`), a full skip of the
fact-checker layer after authoring completes in-budget
(`test_fact_checker_loop_skips_after_budget`), a full skip of gap
detection after fact-checking completes
(`test_gap_detector_loop_skips_after_budget`), and the unlimited-budget
control that authors, fact-checks, and gap-checks everything with zero
`time_budget_exceeded` reasons
(`test_unlimited_budget_authors_all_targets`).

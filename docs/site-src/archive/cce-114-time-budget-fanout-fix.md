---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# CCE-114: Time-Budget Enforcement in the Post-Admission Fan-Out

**Decision date:** 2026-06-16  
**Jira:** CCE-114  
**PR:** #136

## Context

CCE-109 introduced a soft time budget (`DEFAULT_TIME_BUDGET_SECONDS = 2700`, 45 minutes) and a per-PR admission gate that truncates the PR list when the deadline passes. The gate fires during the PR-summarizer loop at `orchestrator_runner.py:1360`.

The scope gap: the budget check fired early — minutes into a run, while all PRs were still being admitted — and then the orchestrator spent the remaining 35-40 minutes in the page-author fan-out with no further checks. Each admitted PR can produce one or more doc-target batches; each batch is one Opus dispatch. A large backlog window could generate ~43 dispatches in the authoring loop alone, all of which would start and run until the 60-minute GitHub Actions hard kill terminated the workflow.

## Incident

Six consecutive scheduled nightly runs (June 5–10, 2026) were killed by the GitHub Actions 60-minute timeout. Run 27263616736 is the forensic anchor: the soft deadline was reached at 09:15:39, but approximately 20 page-author dispatches started after that point and were forcibly terminated when the job was cancelled. Each killed run orphaned an hour of Opus API work and advanced no state. The same window was re-queued at the next nightly, producing the same kill. CCE-109 had broken the doom loop for large PR windows at the admission stage but left the post-admission phases unbounded.

## Decision

Enforce the CCE-109 deadline in all three expensive post-admission loops: the page-author fan-out, the fact-checker loop, and the gap-detector loop. The enforcement posture differs by loop based on correctness requirements:

**Page-author loop** (`orchestrator_runner.py:1440`): same at-least-one-progress guarantee as PR admission — `i > 0` before the gate fires, so the first batch always runs regardless of budget. Partial batches are deferred, not dropped; the cursor advance logic already handles the truncated case.

**Fact-checker loop** (`orchestrator_runner.py:1610`): no at-least-one guarantee. Once the deadline passes, remaining pages are skipped outright. The reason added by `add_partial` is NOT `info_only` — a run with unverified pages must not auto-merge under CCE-101.

**Gap-detector loop** (`orchestrator_runner.py:1725`): same posture as the fact-checker. First gate check fires before the first dispatch; the whole loop is skipped when the deadline has passed.

The decision to use a non-`info_only` partial reason for both advisory loops (fact-checker and gap-detector) is deliberate. `info_only` reasons are excluded from the CCE-101 auto-merge eligibility check; a budget truncation of these loops is a content quality gap, not an infrastructure advisory.

## Implementation

The authoring loop guard is at `orchestrator_runner.py:1433–1446`:

```python
if deadline is not None and i > 0 and clock() > deadline:
    add_partial(
        state,
        f"time_budget_exceeded: authored {i}/{len(per_target)} "
        f"page batches (budget {budget}s); deferring the rest",
    )
    break
```

The fact-checker guard at `orchestrator_runner.py:1603–1617` and the gap-detector guard at `orchestrator_runner.py:1725–1731` follow the same pattern without the `i > 0` floor.

Four TDD-driven tests were added at `tests/orchestrator/test_time_budget_authoring.py`:

- `test_authoring_loop_truncates_after_budget`: verifies that with three doc-target batches and a clock that trips after batch 0, only `alpha.md` is authored and `partial` is true.
- `test_fact_checker_loop_skips_after_budget`: verifies all three pages are authored but fact-checking is skipped entirely when the deadline passes before the first fact-checker gate.
- `test_gap_detector_loop_skips_after_budget`: verifies authoring and fact-checking both complete but gap detection is skipped.
- `test_unlimited_budget_authors_all_targets`: verifies `time_budget_seconds=0` (unlimited) authors all three targets with `partial: false`.

## CCE-101 Interaction

A run truncated in the fact-checker or gap-detector loops produces a non-`info_only` partial reason. The CCE-101 auto-merge gate checks `partial: true` in the PR body (derived from `state["current_run"]["partial"]`); a truncated advisory loop withholds auto-merge correctly. The PR is left open for the operator. The next nightly run picks up where the cursor left off for the authoring phase, but reruns fact-checking and gap-detection from scratch against the full authored set — these loops have no cursor of their own.

## Alternatives Considered

**Carry a per-loop cursor in state.json**: would allow resuming mid-loop across runs, at the cost of significant state-schema complexity and a new class of cursor-coherence bugs. Deferred; the nightly window is designed to be processable in a single run.

**Increase the budget past 45 minutes**: does not fix the structural gap — a sufficiently large backlog still blows any fixed budget. The admission gate + fan-out gate combination is the correct defense.

**Make fact-checker / gap-detector truncations `info_only`**: rejected. A PR body that skipped fact-checking should not auto-merge silently. Operator review is the correct posture for an incomplete run.

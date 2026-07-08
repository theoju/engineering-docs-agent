---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
---

# CCE-114: Time-Budget Enforcement Moves Into the Authoring Fan-Out

**Date:** 2026-06-10 · **PR:** #136 · **Follow-up to:** CCE-109

## The failure

CCE-109 gave the nightly orchestrator a soft time budget (`DEFAULT_TIME_BUDGET_SECONDS = 2700`,
`scripts/orchestrator_runner.py:310` — 45 minutes, under the workflow's
`timeout-minutes: 60` hard kill) and checked it once, in the PR-admission loop:
each iteration past the first compares `clock()` against the deadline and, if
it's blown, truncates the PR list and defers the rest to the next run.

That check runs early. It completes minutes into a run, well before the
expensive work starts. The page-author fan-out — one Claude dispatch per
doc-target batch, and by far the most expensive phase, up to 43 of roughly 50
dispatches in a backlog window — had no deadline check of its own, so it ran
straight through the budget and into the workflow's hard timeout.

The result: six consecutive scheduled nightlies were killed at
`timeout-minutes: 60`, most recently run `27263616736` on 2026-06-10. Each one
discarded a full hour of work and advanced nothing — `last_successful_run`
never moved, so the next nightly re-attempted the same oversized window and
repeated the failure.

## The fix

CCE-114 pushes the deadline check into the loops that actually spend the
budget, not just the one that admits work:

- **Page-author fan-out.** The loop checks the deadline before dispatching
  each doc-target batch. It still guarantees at least one batch runs — the
  same at-least-one-progress guarantee CCE-109 gave PR admission — so a
  budget tight enough to trip on the first check still makes forward
  progress instead of authoring nothing.
- **Fact-checker loop.** Checked before each per-page dispatch; once the
  deadline has passed, the loop skips outright rather than guaranteeing a
  minimum, since it's advisory rather than authoring.
- **Gap-detector loop.** Same skip-outright treatment as the fact-checker
  loop.

Each cut records a `time_budget_exceeded` partial reason naming what was
completed versus the total, e.g. `authored 1/3 page batches`,
`fact-checked 0/3 pages`, or `gap-checked 0/3 PRs` — pinned exactly in
`tests/orchestrator/test_time_budget_authoring.py`.

## Why the fact-checker cutoff flips `partial`, not just logs it

Before CCE-114, a budget cutoff inside the advisory loops would have been
info-only — the run still looked clean. That's wrong for the fact-checker
specifically: CCE-101's auto-merge gate requires zero fact-checker warnings
before it will squash-merge a docs-agent PR. A page that was authored but
never fact-checked because the budget ran out isn't the same as a page that
was fact-checked and passed — treating the cutoff as info-only would let an
unverified page sail through the auto-merge gate. So a fact-checker budget
cutoff now sets `current_run.partial = True`, which the CCE-101 eligibility
check already treats as merge-blocking.

All three cuts — authoring, fact-checker, gap-detector — leave the generated
PR open for operator review rather than discarding the run, the same
graceful-degradation posture CCE-109 established for PR admission: a partial
run is a visible operational signal, never a silent one.

## Verification

`tests/orchestrator/test_time_budget_authoring.py` pins four cases against a
three-target fixture (`fakes_multi` with `doc_targets` expanded to three
`connectors/{alpha,beta,gamma}.md` pages via a fake clock sequence):

- authoring truncates after the budget (batch 0 always runs; batches 1–2 are
  deferred, and only `alpha.md` lands on disk),
- the fact-checker loop skips its whole warn layer once the deadline has
  passed (authoring itself is unaffected — all three pages still exist),
- the gap-detector loop skips once the deadline has passed, and does so
  without leaving a stray `fact-checked` reason behind it,
- an unlimited budget (`time_budget_seconds=0`) authors all three targets and
  never emits a `time_budget_exceeded` reason.

## References

- PR #136 (CCE-114)
- `scripts/orchestrator_runner.py` — `resolve_time_budget`, the admission
  loop's existing deadline guard, and the new authoring/fact-checker/
  gap-detector guards
- `tests/orchestrator/test_time_budget_authoring.py`
- Prior decision: soft time budget for the nightly orchestrator runner
  (CCE-109) — established the budget and the admission-loop guard this
  page's fix extends
- CCE-101 merge-gate design (`docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md`)
  — the auto-merge eligibility check that motivates flipping `partial` on a
  fact-checker cutoff

---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# Time-budget enforcement now covers the authoring fan-out (CCE-114)

CCE-109 gave the nightly orchestrator a soft deadline, but the check only
ran between PR admissions — which finish minutes into a run. Everything
after admission, including the page-author fan-out, ran unbounded. Six
consecutive scheduled nightlies (June 5–10) blew through the deadline and
died at the workflow's hard `timeout-minutes: 60` kill mid-fan-out, each
time discarding up to 43 of ~50 planned dispatches with no PR opened and
no baseline advance. Forensics on run `27263616736` pinned the failure to
roughly 20 page-author dispatches starting after the deadline had already
passed. CCE-114 closes the gap by pushing the deadline check into the
loops that actually spend the run's time budget.

## What changed

`scripts/orchestrator_runner.py` now checks `deadline`/`clock()` inside
three loops, not just at admission:

- **Authoring loop** (`orchestrator_runner.py:1440`). Before dispatching
  each doc-target batch, the loop checks `deadline is not None and i > 0
  and clock() > deadline`. The `i > 0` guard mirrors the admission-loop's
  at-least-one-progress rule — batch 0 always runs even on an already-blown
  budget, so a tight window still makes forward progress instead of
  authoring nothing. On trip, it records
  `time_budget_exceeded: authored {i}/{N} page batches (budget {budget}s);
  deferring the rest` and breaks.
- **Fact-checker loop** (`orchestrator_runner.py:1610`). Before dispatching
  the fact-checker for each authored page that cites a resolvable source,
  the loop checks `deadline is not None and clock() > deadline` — no
  at-least-one guarantee here, because this is an advisory pass over pages
  that already exist on disk, not primary content production. On trip, it
  records `time_budget_exceeded: fact-checked {i}/{N} pages (budget
  {budget}s); skipping the rest` and breaks.
- **Gap-detector loop** (`orchestrator_runner.py:1725`). Same skip-outright
  pattern, per PR: `time_budget_exceeded: gap-checked {i}/{N} PRs (budget
  {budget}s); skipping the rest`.

The fact-checker and gap-detector cuts are the one place where an
advisory-layer failure is deliberately *not* marked `info_only`. Every
other fact-checker/gap-detector reason in the same code (unavailable
dispatch, contradiction findings) uses `info_only=True` so it can't flip
the run to partial. The CCE-114 time-budget cut is the sole exception: a
page that was never fact-checked must not slip through the CCE-101
auto-merge gate (which requires `partial=False`), so this specific reason
is recorded as a hard partial.

All three cuts leave the PR open for an operator to review rather than
blocking it outright — merging accepts the coverage loss for that run,
and not merging retries the window on the next nightly.

## Why this shape

The authoring loop is the expensive phase: one Claude dispatch per
doc-target batch, and in a backlog window that can be the bulk of the
run's ~50 total dispatches. Gating only at admission left it completely
unbounded once PRs were admitted. The fix follows the same pattern CCE-109
already established for admission — check `clock() > deadline`, record a
`time_budget_exceeded` partial reason, stop — just applied at each phase
boundary where the orchestrator is about to spend real wall-clock time.

`tests/orchestrator/test_time_budget_authoring.py` pins all three loops
with a fake monotonic clock: `test_authoring_loop_truncates_after_budget`
confirms batch 0 authors even when the deadline has already passed at
batch 1's gate; `test_fact_checker_loop_skips_after_budget` confirms
authoring completes untouched while the fact-checker layer skips
entirely; `test_gap_detector_loop_skips_after_budget` confirms the
gap-detector cut fires independently of the fact-checker one; and
`test_unlimited_budget_authors_all_targets` confirms `time_budget_seconds=0`
(unlimited) authors every target with no `time_budget_exceeded` reasons at
all.

See the `[Unreleased]` entry in `CHANGELOG.md` for the release note, and
`docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md` for how
`partial` feeds the CCE-101 auto-merge gate that this fix protects.

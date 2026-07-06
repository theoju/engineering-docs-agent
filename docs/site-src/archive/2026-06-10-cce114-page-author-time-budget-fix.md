---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# CCE-114: Time Budget Now Bounds the Page-Author Fan-Out

## Context

CCE-109 introduced a soft time budget (`resolve_time_budget` in `scripts/orchestrator_runner.py`, default `DEFAULT_TIME_BUDGET_SECONDS = 2700` — 45 minutes, chosen to sit below the workflow's 60-minute hard kill) so a large backlog window would truncate cleanly instead of running unbounded. The deadline check lived in exactly one place: the PR-admission loop in `run()`, gated on `deadline is not None and i > 0 and clock() > deadline`.

That one check wasn't enough. Admission is cheap — it completes minutes into a run. The expensive phase is everything downstream of it: the page-author fan-out (one Claude dispatch per doc-target batch), the fact-checker loop, and the gap-detector loop. None of the three consulted the deadline. On a large backlog window, admission would finish inside budget, and then the page-author fan-out — up to 43 of roughly 50 dispatches in the observed backlog case — ran straight past the deadline into the workflow's 60-minute job timeout. Run `27263616736` is the pinned example: ~20 page-author dispatches started after the deadline had already passed.

The practical effect was CCE-109's doom loop recurring in a new shape: six consecutive scheduled nightlies (2026-06-05 through 2026-06-10) died at the hard kill with zero progress and no state advance — the exact failure mode CCE-109 was supposed to close, just relocated to a stage the original fix didn't cover.

## Fix

CCE-114 extends the same deadline check into the three post-admission loops, following the tests in `tests/orchestrator/test_time_budget_authoring.py`:

- **Page-author loop.** Checked before each doc-target batch (not before every individual page — batches are the actual dispatch unit). Like the admission loop, the first batch always dispatches regardless of the clock, so a tight budget still guarantees at least one unit of forward progress rather than truncating to zero pages. `test_authoring_loop_truncates_after_budget` pins this: with a 3-batch fan-out and a deadline that trips before batch 2, exactly one page (`alpha.md`) gets written, and the partial reason reads `time_budget_exceeded: authored 1/3 page batches`.
- **Fact-checker loop.** Checked before each page's fact-check dispatch. Unlike the authoring loop, this loop has no at-least-one guarantee — it's advisory and skips outright once the deadline is past, per `test_fact_checker_loop_skips_after_budget`'s `time_budget_exceeded: fact-checked 0/3 pages` reason. Authoring itself is unaffected by this cut: all 3 pages from that test's fully-authored run remain on disk.
- **Gap-detector loop.** Same skip-outright pattern, checked before each PR's gap-detection dispatch. `test_gap_detector_loop_skips_after_budget` pins the `time_budget_exceeded: gap-checked 0/3 PRs` reason and confirms the fact-checker loop's reasons are absent when the deadline trips before that loop even starts.

All three cuts call `add_partial(state, ...)`, so `current_run.partial` flips to `True` on any truncation. That matters beyond visibility: the CCE-101 auto-merge gate requires a non-partial run, so a run that skipped fact-checking or gap-detection under time pressure cannot slip through to auto-merge — the same invariant CCE-109 established for admission-level truncation now holds for the more expensive stages that actually consume most of a run's wall-clock time.

An unlimited budget (`time_budget_seconds=0`) still authors, fact-checks, and gap-checks every target with no truncation — `test_unlimited_budget_authors_all_targets` covers the zero-budget passthrough, matching `resolve_time_budget`'s existing "a value <= 0 means unlimited" contract.

## Why this shape

The deadline check is duplicated per-loop rather than factored into a single shared gate, because the loops have two genuinely different truncation policies:

- Admission and authoring both need **at-least-one-progress**: a nightly that produces zero admitted PRs or zero authored pages wastes the run entirely, so the first unit of work in each of those loops is unconditional.
- Fact-checking and gap-detection are **advisory** passes over work that authoring already committed to disk. Skipping them outright when the deadline has passed is strictly safer than the at-least-one-progress rule — the `partial` flag already blocks auto-merge, so there is no benefit to guaranteeing one more advisory dispatch at the cost of run predictability.

All four cuts still finish the run and leave the PR open for operator review rather than aborting — consistent with the existing CCE-109/D3 invariant that a truncated or partial run is a visible, actionable PR state, never a silent failure or a bare non-zero exit.

## See also

- `docs/site-src/archive/2026-06-10-cce109-doom-loop-resolution.md` — the incident that motivated CCE-109's original admission-level budget.
- `scripts/orchestrator_runner.py` — `resolve_time_budget`, `DEFAULT_TIME_BUDGET_SECONDS`, and the admission loop's `time_budget_exceeded` guard this fix mirrors.
- `tests/orchestrator/test_time_budget_authoring.py` — the four tests pinning this fix's behavior.
- CHANGELOG.md, `[Unreleased]` — "CCE-109 time budget now bounds the authoring fan-out (CCE-114)."

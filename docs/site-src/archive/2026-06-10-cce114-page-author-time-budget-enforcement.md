---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# CCE-114: Time-Budget Enforcement Reaches the Page-Author Fan-Out

## Context

CCE-109 gave the nightly runner a soft time budget (`resolve_time_budget`, `scripts/orchestrator_runner.py:339`) and a deadline check at PR admission (`scripts/orchestrator_runner.py:1394`): once the deadline passes, admission truncates to an oldest-first prefix, flips `partial`, and defers the rest to the next window. That closed the doom loop documented in the 2026-06-10 CCE-109 archive entry — but only at the front of the pipeline.

Admission finishes minutes into a run. Everything after it — page-author dispatch, the fact-checker warn layer, gap detection — ran with no deadline check at all. The page-author fan-out is the expensive part: one Claude dispatch per `(lens, page_hint)` batch (`scripts/orchestrator_runner.py:1467`), not per PR. A window with a large PR count but few, fully-admitted PRs could still fan out into dozens of authoring dispatches, none of which ever looked at the clock.

## What happened

Six consecutive scheduled nightlies, 2026-06-05 through 2026-06-10, died at the workflow's hard 60-minute job timeout. Every one of them had already passed admission — `last_successful_run` never advanced, and no PR opened, so each failed run's cost (an hour of Opus dispatches) was discarded outright and the next nightly re-attempted the same window from scratch.

CCE-114 forensics on one killed run (27263616736) found 43 of ~50 total subagent dispatches were page-author calls, and roughly 20 of those started after the CCE-109 soft deadline had already elapsed. The soft-deadline fix had shipped; it just didn't reach the loop that actually burns the clock.

## Decision

Extend the same deadline check (`deadline is not None and clock() > deadline`) into the three loops downstream of admission, each with a posture suited to how the loop treats missed pages:

**Page-author fan-out** (`scripts/orchestrator_runner.py:1474`) — gated per batch, before dispatch, with the same at-least-one-progress guarantee admission uses (`i > 0`): batch 0 always runs even if the deadline has already passed, so a run can't zero-progress forever. A trip records `time_budget_exceeded: authored {i}/{n} page batches` and flips `partial`.

**Fact-checker loop** (`scripts/orchestrator_runner.py:1671`) — gated per page, with no at-least-one exemption: this loop is advisory (it warns, never blocks a page), so there's no progress guarantee to preserve. The important change from CCE-109's admission precedent is that this cut is **not** `info_only`. A page whose citations were never fact-checked must not be eligible for the CCE-101 auto-merge gate, so `time_budget_exceeded: fact-checked {i}/{n} pages` flips `partial` like any other authoring-path reason.

**Gap-detector loop** (`scripts/orchestrator_runner.py:1786`) — same skip-and-partial posture as the fact-checker: gated per PR, no at-least-one exemption, `time_budget_exceeded: gap-checked {i}/{n} PRs` flips `partial`.

All three cuts leave the PR open rather than failing the run: the operator sees the partial reason, the truncated page set, and can either accept the coverage loss for that nightly or accept the PR and let the next run's window pick up where this one stopped.

## Why the fact-checker exception matters

CCE-110 established the fact-checker as strictly warn-only: a contradiction finding never drops a page and never flips `partial` on its own. CCE-101's auto-merge gate then keys eligibility off `partial == false` AND zero fact-checker warnings — but that gate has no way to distinguish "fact-checker ran and found nothing" from "fact-checker never ran." Leaving the CCE-114 time-budget cut `info_only` would have created exactly that hole: a page authored late in a long run could skip fact-checking and still auto-merge clean. Flipping `partial` on the cut (not on the checker's verdict) closes it without touching CCE-110's underlying warn-only contract for findings that do run.

## Verification

`tests/orchestrator/test_time_budget_authoring.py` pins all four cases against a fixture that fans one PR summary out into three doc-target batches (`connectors/{alpha,beta,gamma}.md`):

- `test_authoring_loop_truncates_after_budget` — clock trips before batch 1; `alpha.md` is written, `beta.md`/`gamma.md` are not; `partial_reasons` records `authored 1/3 page batches`.
- `test_fact_checker_loop_skips_after_budget` — authoring completes (all 3 pages exist), the clock trips before the first fact-check dispatch; `partial_reasons` records `fact-checked 0/3 pages`; authoring output itself is untouched.
- `test_gap_detector_loop_skips_after_budget` — authoring and fact-checking both complete inside budget, the clock trips before gap detection; `partial_reasons` records `gap-checked 0/3 PRs` and carries no `fact-checked` reason.
- `test_unlimited_budget_authors_all_targets` — `time_budget_seconds=0` (unlimited) authors all three pages with `partial` staying `false`, confirming the new gates are no-ops when no budget is configured.

## See also

- `docs/site-src/archive/2026-06-10-cce109-doom-loop-resolution.md` — the originating incident and the admission-side soft-deadline fix this PR extends.
- `docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md` — the auto-merge eligibility gate that the fact-checker `partial` flip protects.
- `tests/orchestrator/test_time_budget_authoring.py` — the four pinned cases above.

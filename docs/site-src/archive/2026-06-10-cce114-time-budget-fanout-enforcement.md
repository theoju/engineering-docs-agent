---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# CCE-114: time-budget enforcement in the authoring fan-out

CCE-109's soft deadline was checked once, at PR admission, which completes minutes into a run. Every stage after admission — the page-author fan-out, the fact-checker warn layer, the gap-detector loop — ran with no deadline check at all, and the sixth consecutive nightly died at the workflow's 60-minute hard kill with all work discarded. CCE-114 closes the gap by checking the deadline before every batch in every fan-out loop, not just before the PR list is truncated.

## Incident

Forensics on run `27263616736` (2026-06-10) found admission's deadline check completing early — all PRs in the window were admitted well inside the 45-minute soft budget (`DEFAULT_TIME_BUDGET_SECONDS`, `scripts/orchestrator_runner.py:310`). The page-author fan-out then ran unbounded: roughly 20 page-author dispatches started after the soft deadline had already passed, and the job was killed by the CI workflow's 60-minute hard timeout before any of them — or the fact-checker and gap-detector stages behind them — completed.

Because the run never reached its end-of-run state write, `state.json.last_successful_run` never advanced. This was the sixth consecutive nightly to die this way. Each one discarded a full hour of authoring work and left the baseline exactly where the previous failed run had left it, so the next night's window only grew.

CCE-109 had closed the *admission-time* half of this problem: the PR-admission loop (`scripts/orchestrator_runner.py:1394-1409`) already checks the deadline before admitting each PR past the first, truncating the PR list and deferring the remainder to the next run. That guarantee held — it was just checking the wrong choke point. Admission is cheap; authoring, fact-checking, and gap-detection are where a run's wall-clock time actually goes.

## Decision

Check the deadline before every batch in every fan-out loop that runs after admission, not only before the loop that produces the PR list:

- **Page-author fan-out** (`scripts/orchestrator_runner.py:1467-1480`): before dispatching each `(lens, page_hint)` batch, check `clock() > deadline`. On trip, record `time_budget_exceeded: authored {i}/{n} page batches (budget {budget}s); deferring the rest` and stop — the remaining batches are simply never dispatched this run. The guard mirrors admission's `i > 0` at-least-one-progress rule: batch 0 always runs unconditionally, so a budget so tight it would trip immediately still makes forward progress instead of authoring nothing.
- **Fact-checker warn loop** (`scripts/orchestrator_runner.py:1664-1678`): before fact-checking each already-authored page, check the same deadline. On trip, record `time_budget_exceeded: fact-checked {i}/{n} pages (budget {budget}s); skipping the rest` and stop. There is no at-least-one guarantee here — the loop is advisory, so a budget already exhausted by authoring skips it outright rather than spending one more dispatch it can't afford.
- **Gap-detector loop** (`scripts/orchestrator_runner.py:1783-1792`): same posture as the fact-checker — checked before each PR, skips outright with `time_budget_exceeded: gap-checked {i}/{n} PRs (budget {budget}s); skipping the rest` once tripped.

An unlimited budget (`time_budget_seconds=0`, or a negative CLI override) resolves `deadline` to `None` (`resolve_time_budget`, `scripts/orchestrator_runner.py:339-352`), and every one of the three checks above short-circuits on `deadline is not None`. Nothing changes for a host that opts out of budgeting.

## Why the fact-checker skip flips `partial`

Every other CCE-114 budget cut is orthogonal to correctness — deferring a PR or a page batch to the next run is safe because nothing downstream depends on it having run. The fact-checker skip is different: CCE-101's auto-merge gate requires `partial == false` **and** zero fact-checker contradiction warnings. Before this fix, a fact-checker skip logged an `info_only` reason and left `partial` untouched — a page that was never fact-checked would report zero warnings (because it was never checked at all) and sail through the CCE-101 gate as if it had passed.

`scripts/orchestrator_runner.py:1671-1678` records the fact-checker skip as a regular (non-`info_only`) partial reason for exactly this reason: a page that skipped fact-checking must not be indistinguishable from a page that passed it. Every other reason inside the fact-checker loop — dispatch failures, `fact_checker_unavailable`, prose-contamination rescues — stays `info_only=True`, unchanged; only the CCE-114 budget-trip reason is loud.

## What did not change

- All three cuts still leave the PR open. A budget-triggered `partial: true` run is exactly the existing "operator reviews and retries" path CCE-101 already has for any other partial run — CCE-114 adds no new failure UX.
- Authoring itself is never retroactively undone by a later loop's skip. `tests/orchestrator/test_time_budget_authoring.py::test_fact_checker_loop_skips_after_budget` pins this: all three pages in that fixture are authored before the fact-checker loop trips, and all three remain on disk after the run — the skip drops the check, not the content.
- Content validation and the deterministic site generators are unaffected; only the three loops named above gained a deadline check.

## References

- Ticket: CCE-114 (closes the fan-out half of the gap CCE-109 opened at admission).
- PR: [#136](https://github.com/theoju/engineering-docs-agent/pull/136).
- Tests: `tests/orchestrator/test_time_budget_authoring.py` — truncation after budget in the authoring loop, skip-outright in the fact-checker and gap-detector loops, and the unlimited-budget control case.
- Prior art: CCE-109 (admission-time deadline check; `scripts/orchestrator_runner.py:1394-1409`), CCE-101 (the auto-merge gate this fix protects; `docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md`).

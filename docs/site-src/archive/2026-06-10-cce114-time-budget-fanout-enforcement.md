---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
---

# Decision: Time-Budget Enforcement in the Post-Admission Fan-Out Loops (CCE-114)

- **Ticket:** CCE-114
- **Date:** 2026-06-10
- **Decision:** the CCE-109 soft time deadline is now checked inside all three per-run fan-out loops — page-author, fact-checker, and gap-detector — not just at PR admission.

## Problem

CCE-109 gave the nightly orchestrator a soft time budget (`resolve_time_budget` in `scripts/orchestrator_runner.py`, default `DEFAULT_TIME_BUDGET_SECONDS = 2700`, 45 minutes — comfortably under the workflow's 60-minute hard kill). But the deadline check lived in exactly one place: the PR-admission loop, which truncates the PR list before any authoring work starts.

Admission is cheap. The page-author fan-out that follows it is not — up to ~50 Opus dispatches in a single run, one per doc-target batch. Nothing re-checked the deadline once admission finished, so a run that admitted its full PR backlog in minutes could then blow through authoring, fact-checking, and gap-detection with no budget guard at all.

Forensics on run `27263616736` showed the failure mode directly: roughly 20 of 43 page-author dispatches started **after** the 09:15:39 deadline had already passed. The job ran until the workflow's hard 60-minute timeout killed it, and everything — all authored pages, all state — was discarded. That was the sixth consecutive scheduled nightly (June 5–10) to die this way. Each one burned about an hour of compute and left `state.json.last_successful_run` untouched, so the next night picked up the identical backlog and repeated the cycle. This is the same doom loop CCE-109 was supposed to close; CCE-109 closed the admission half and left the fan-out half open.

## Fix

Three separate gates, one per loop, matching each loop's cost profile and its position relative to the CCE-101 auto-merge gate:

- **Page-author (authoring) loop.** Before dispatching each doc-target batch, check the deadline. This mirrors admission's at-least-one-progress guarantee: the first batch always dispatches unconditionally, so even a run with zero budget remaining still produces one authored batch rather than none. Every batch after the first is gated. A cut records `time_budget_exceeded: authored <n>/<total> page batches` in `partial_reasons` and flips `partial` to `true`.
- **Fact-checker loop.** Once the deadline has passed, the loop skips outright rather than gating per-page — there is no partial-credit case to protect, because a page that hasn't been fact-checked yet must not be treated as though it passed. The reason recorded is `time_budget_exceeded: fact-checked <n>/<total> pages`. Critically, this flips `partial = true` (not merely an info-only note): an unverified page can no longer slip past the CCE-101 auto-merge gate, which requires `partial == false` AND zero fact-checker warnings. Before this fix, a page skipped for time reasons carried no fact-checker warning at all — it looked clean to the merge gate precisely because it was never examined.
- **Gap-detector loop.** Same skip-outright pattern, recording `time_budget_exceeded: gap-checked <n>/<total> PRs`. Gap flags are advisory and never block merge on their own, but a cut here still needs to be visible in the run record — a docs-agent PR that silently skipped gap detection under time pressure should not read as identical to one that ran it clean.

In all three cases the run still proceeds through lint and PR-open tail work rather than aborting. The PR opens (or gets an append-commit) with `partial: true` and the specific `time_budget_exceeded` reasons visible in the body, so an operator can accept the coverage loss for that night or let the next scheduled run retry the deferred work.

An unlimited budget (`time_budget_seconds: 0`, or CLI override `0`) disables all three gates — `resolve_time_budget` returns a non-positive value, `run()` sets `deadline = None`, and every loop runs to completion with `partial` staying `false`.

## Tests

`tests/orchestrator/test_time_budget_authoring.py` pins all four cases against a shared three-batch fixture (`fakes_multi` copied with `doc_targets` expanded to three distinct pages):

- `test_authoring_loop_truncates_after_budget` — deadline trips mid-authoring; batch 0 (`alpha.md`) is written unconditionally, batches 1–2 (`beta.md`, `gamma.md`) never dispatch; `partial_reasons` shows `authored 1/3 page batches`.
- `test_fact_checker_loop_skips_after_budget` — authoring completes inside budget (all three pages exist, including `gamma.md`), but the deadline trips before the fact-checker loop starts; it skips entirely (`fact-checked 0/3 pages`) without touching the already-authored pages.
- `test_gap_detector_loop_skips_after_budget` — fact-checking completes clean (dry-run pages cite nothing, so it dispatches nothing but still passes its own gates), the deadline trips before gap-detection; `gap-checked 0/3 PRs` is recorded and no `fact-checked` cut reason appears — confirming the fact-checker loop truly finished rather than also being cut.
- `test_unlimited_budget_authors_all_targets` — `time_budget_seconds: 0` authors all three pages, `partial` stays `false`, and no `time_budget_exceeded` reason appears anywhere.

## Consequence

The nightly run's cost is now bounded end-to-end by the same clock, not just at the cheapest of its four stages. A run under time pressure degrades to a smaller, explicitly-flagged partial PR instead of dying uncommitted at the workflow's hard timeout. See also `docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md` for how `partial` and fact-checker warnings gate auto-merge, and the CCE-109 archive entry for the admission-side half of this budget.

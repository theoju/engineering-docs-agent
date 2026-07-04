---
description: 'Documents the CCE-109 soft time budget and its CCE-114 extension into the page-author, fact-checker, and gap-detector loops'
source_files:
  - CHANGELOG.md
  - scripts/orchestrator_runner.py
  - tests/orchestrator/test_time_budget_authoring.py
last_reviewed: '2026-07-04'
status: draft
doc_kind: architecture
---

# Time budget enforcement

The nightly run carries a soft time budget, separate from the GitHub Actions job's hard 60-minute timeout. The budget exists so the orchestrator can stop cleanly — commit what it has, open a partial PR, and defer the rest to the next nightly — instead of getting killed mid-flight with nothing to show for the run.

## The budget itself

`resolve_time_budget` (`scripts/orchestrator_runner.py:339`) resolves the per-run budget in seconds, in this precedence order:

1. A CLI override (including an explicit `0`, which means unlimited).
2. `run.time_budget_seconds` in the host's config.
3. `DEFAULT_TIME_BUDGET_SECONDS` — 2700 seconds (45 minutes), chosen to sit safely below the workflow's 60-minute hard limit (`scripts/orchestrator_runner.py:310`).

`run()` turns that into a monotonic `deadline` once per invocation (`clock() + budget`), or `None` when the budget resolves to `<= 0`. Every gate described below checks `deadline is not None and clock() > deadline` — a budget of `0` disables enforcement entirely rather than tripping immediately.

## Where CCE-109 originally checked it: PR admission

The budget's first consumer was the PR-admission loop: as `source-collector` output is walked PR-by-PR, each iteration (after the first — `i > 0`, so a single huge PR can never be starved out) checks the deadline before summarizing the next PR. Once tripped, the loop truncates `prs` to the admitted prefix and records `time_budget_exceeded: admitted {i}/{len(prs)} PRs`. Everything downstream then advances the baseline only to a confirmed-safe cursor (`_sha_in_window`, `_last_processed_merge_sha`) — never past an unanchored deferred PR — so a truncated run loses no history and never regresses the baseline.

Admission alone wasn't enough. It finishes minutes into a run because summarizing a PR is comparatively cheap; the expensive work — page authoring, fact-checking, gap detection — was still unbounded.

## CCE-114: extending the deadline into the three expensive loops

Six consecutive scheduled nightlies (2026-06-05 through 2026-06-10) died at the workflow's hard 60-minute kill with no PR opened and no state advance. Page-author dispatches accounted for the bulk of a run's Claude calls — 43 of roughly 50 dispatches in the CCE-114 forensics window — and none of them checked the budget, so the fan-out kept issuing Opus calls straight through the deadline. Forensics on the incident run (27263616736) counted roughly 20 page-author dispatches that started only *after* the soft deadline had already passed. CCE-114 closes that gap by adding the same deadline check to the three loops that run after admission:

### Page-author fan-out

`per_target.items()` batches doc targets by `(lens, page_hint)` and dispatches one `page-author` call per batch (`scripts/orchestrator_runner.py:1467`). The gate mirrors admission's shape exactly: checked only when `i > 0`, so the loop still makes at-least-one-batch progress even if the deadline was already blown by the time authoring started. On trip, it records `time_budget_exceeded: authored {i}/{len(per_target)} page batches (budget {budget}s); deferring the rest` and `break`s — batches already authored keep their files; the rest are simply never dispatched, to be picked up (or re-summarized) on the next nightly.

### Fact-checker loop (warn layer)

The fact-checker loop is advisory by design — a `fact-checker` verdict never blocks a page or forces a partial run on its own (`scripts/orchestrator_runner.py:1648`). CCE-114 makes one exception. The deadline check here (`scripts/orchestrator_runner.py:1671`) has no at-least-one-progress carve-out: it checks before *every* page, including the first, because every second spent past the deadline risks the hard kill. When it trips, the loop records `time_budget_exceeded: fact-checked {i}/{len(fact_pages)} pages (budget {budget}s); skipping the rest` — and, unlike every other reason recorded in this loop (which is `info_only=True`), this one is **not** marked info-only. A page that was authored but never fact-checked must not silently sail through the CCE-101 auto-merge gate, which keys off `partial`. Flipping partial here forces the run to stay open for an operator to review the coverage gap.

### Gap-detector loop

Same posture as the fact-checker: `scripts/orchestrator_runner.py:1783` checks the deadline before every PR (no `i > 0` exemption), and on trip records `time_budget_exceeded: gap-checked {i}/{len(prs)} PRs (budget {budget}s); skipping the rest` as a non-info-only reason — the run goes partial rather than silently shipping with unchecked gap detection.

## What a cut run looks like to an operator

All three cuts leave the run's PR open rather than failing the run outright. `state.json.current_run.partial` is `True`, `partial_reasons` names exactly which loop was cut and how far it got, and the CCE-101 auto-merge gate refuses to auto-merge (auto-merge requires non-partial *and* zero fact-checker warnings). The operator has two choices: accept the coverage loss and merge manually, or let the next nightly retry — admission's baseline-advance safety net means a truncated run never loses or re-orders PRs regardless of which loop got cut.

## Tests

`tests/orchestrator/test_time_budget_authoring.py` pins all three gates with a fake monotonic clock: `test_authoring_loop_truncates_after_budget`, `test_fact_checker_loop_skips_after_budget`, `test_gap_detector_loop_skips_after_budget`, and `test_unlimited_budget_authors_all_targets` (budget `0` — confirms the disable path authors every target with `partial` staying `False`).

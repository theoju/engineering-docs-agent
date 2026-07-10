---
description: 'Documents the nightly orchestrator pipeline in scripts/orchestrator_runner.py and how it enforces its soft time budget across every fan-out loop, not just PR admission.'
source_files:
  - scripts/orchestrator_runner.py
  - tests/orchestrator/test_time_budget_authoring.py
  - CHANGELOG.md
last_reviewed: '2026-07-10'
status: draft
doc_kind: architecture
---

# Orchestrator

`scripts/orchestrator_runner.py:run()` is the nightly docs-agent pipeline. It turns a window of merged PRs (and, when configured, Jira issues) into a single `docs-agent/YYYY-MM-DD` PR. The pipeline is a sequence of dispatch loops — some mandatory, some advisory — each of which can go partial independently. This page documents the loop structure and, in detail, how the CCE-109/CCE-114 soft time budget is enforced across all of them.

## Pipeline phases

In order, `run()`:

1. Resolves the time budget and computes a monotonic `deadline` (`resolve_time_budget`, `scripts/orchestrator_runner.py:339`).
2. Dispatches `source-collector` for the PR/Jira window, then clips out-of-window PRs and orders them oldest-first (`_clip_prs_to_window`, `_order_prs_oldest_first`).
3. Admits PRs one at a time, dispatching `pr-summarizer` per PR (the admission loop, `scripts/orchestrator_runner.py:1393`).
4. Batches the summaries' `doc_targets` by `(lens, page_hint)` and fans out one `page-author` dispatch per batch (the authoring loop, `scripts/orchestrator_runner.py:1467`).
5. Runs `content-validator` over every authored page and reverts/deletes any page with a `block`-severity lint failure.
6. Runs the advisory `fact-checker` against pages that cite resolvable repo sources (the fact-checker loop, `scripts/orchestrator_runner.py:1664`).
7. Runs the deterministic site generators (archive, contracts, section overviews) when the host config has a `site:` block.
8. Computes source drift (M), citation drift (C1), and canonical-core drift (C2) — all read-only, best-effort stages.
9. Runs the advisory `gap-detector` per admitted PR (the gap-detector loop, `scripts/orchestrator_runner.py:1783`).
10. Composes the What's New entry and, unless `--no-pr`, opens or appends to the nightly PR.

Every dispatch loop routes its per-item failures through `add_partial(state, reason, info_only=...)`. A non-`info_only` reason flips `state["current_run"]["partial"] = True`, which matters downstream: CCE-101's auto-merge gate only fires for a non-partial run with zero fact-checker warnings and no human commits on the PR.

## Time-budget enforcement across the fan-out loops (CCE-109 / CCE-114)

`resolve_time_budget` (`scripts/orchestrator_runner.py:339`) resolves the per-run soft budget: CLI override (including an explicit `0` for unlimited) beats `run.time_budget_seconds` in config, which beats `DEFAULT_TIME_BUDGET_SECONDS` (2700s / 45 minutes — comfortably under the workflow's `timeout-minutes: 60` hard kill). `run()` turns that into a monotonic `deadline = clock() + budget` (`None` when the budget is `<= 0`, i.e. unlimited).

CCE-109 originally gated only PR **admission** on this deadline (`scripts/orchestrator_runner.py:1394`, inside the `for i, pr in enumerate(prs)` loop). That loop follows an at-least-one-progress guarantee: the check is `if deadline is not None and i > 0 and clock() > deadline`, so a budget too tight to admit even one PR still processes the first one rather than opening an empty PR every run.

That admission-only check wasn't sufficient. Admission is cheap — it completes minutes into a run — and the **page-author fan-out** is the expensive phase: one Claude dispatch per `(lens, page_hint)` batch, and in the observed backlog window it accounted for 43 of roughly 50 subagent dispatches. Six consecutive scheduled nightlies (2026-06-05 through 2026-06-10) ran straight through the soft deadline into the workflow's 60-minute hard kill — an hour of Opus dispatches discarded each time, no PR opened, no baseline advance. Forensics from run 27263616736 showed roughly 20 page-author dispatches starting after the computed deadline had already passed.

CCE-114 closes that gap by checking the deadline in three more places, with different postures depending on how expensive skipping is versus how much correctness matters:

- **Authoring loop** (`scripts/orchestrator_runner.py:1474`, inside `for i, ((lens, hint), batch_summaries) in enumerate(per_target.items())`): same at-least-one-progress guarantee as admission — `if deadline is not None and i > 0 and clock() > deadline` — so a tight budget still authors the first batch. On trip, `add_partial` records `time_budget_exceeded: authored {i}/{len(per_target)} page batches (budget {budget}s); deferring the rest` and the loop breaks; pages already authored are kept.
- **Fact-checker loop** (`scripts/orchestrator_runner.py:1671`, inside the per-page loop over `fact_pages`): no at-least-one-progress guarantee — the check is unconditional (`if deadline is not None and clock() > deadline`), because this is an advisory warn layer running after authoring is already done, and every post-deadline second spent here is pure risk against the hard kill. The reason recorded is `time_budget_exceeded: fact-checked {i}/{len(fact_pages)} pages (budget {budget}s); skipping the rest`.
- **Gap-detector loop** (`scripts/orchestrator_runner.py:1786`, inside `for i, pr in enumerate(prs)`): same unconditional posture as the fact-checker loop, recording `time_budget_exceeded: gap-checked {i}/{len(prs)} PRs (budget {budget}s); skipping the rest`.

The fact-checker and gap-detector skips are deliberately **not** `info_only`. Everywhere else in the pipeline, an advisory-stage failure is `info_only=True` so it can't flip the run to partial — but a page that was never fact-checked must not silently qualify for CCE-101 auto-merge as if it had passed. Making these two skip reasons ordinary (non-info-only) `partial` reasons is what keeps that gate honest: any deadline-truncated run stays partial, stays open for operator review, and never advances `state.json.last_successful_run` on its own.

All four truncation paths — admission, authoring, fact-checker, gap-detector — leave the PR open rather than discarding the run. That's the same posture as every other partial-run path in the orchestrator: a partial nightly is a visible operational gap, not a silent failure.

`tests/orchestrator/test_time_budget_authoring.py` pins this behavior with a fake monotonic clock and a three-target fixture (`fakes_multi` with `doc_targets` overridden to three distinct `connectors/{alpha,beta,gamma}.md` pages):

- `test_authoring_loop_truncates_after_budget` — deadline trips before batch 1; only `alpha.md` is written.
- `test_fact_checker_loop_skips_after_budget` — authoring completes all three pages, but the fact-checker loop's first gate trips; `gamma.md` still exists (authoring itself wasn't cut) but no page was fact-checked.
- `test_gap_detector_loop_skips_after_budget` — authoring and fact-checking both complete inside budget; the gap-detector loop's first gate trips.
- `test_unlimited_budget_authors_all_targets` — `time_budget_seconds=0` disables the deadline entirely (`deadline=None`); all three pages are authored and the run is non-partial.

## Related

- CCE-101's auto-merge gate (`docs-agent PRs auto-merge by default`) is documented in `CLAUDE.md` and consumes the `partial` flag this page describes.
- The admission-loop invariant guard (`_sha_in_window`, `_last_processed_merge_sha`) that decides whether a truncated run is even safe to advance the baseline for lives alongside the admission loop in `scripts/orchestrator_runner.py`.

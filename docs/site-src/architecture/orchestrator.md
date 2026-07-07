---
description: 'Documents architecture orchestrator: The orchestrator''s soft time-budget deadline was previously checked only once, at PR admission, which happens minutes into a run. The page-author fan-out (one Opus dispatch per doc-target batch) could then run unbounded well past the deadline, and the whole job was killed by the hard 60-minute CI timeout, discarding all work. This PR adds a deadline check before each authoring batch (preserving admission''s at-least-one-progress guarantee so tight budgets still make forward progress), and makes the fact-checker and gap-detector loops skip outright once the budget has expired. Critically, the fact-checker skip now flips the run''s `partial` flag rather than just logging info, so pages that were never fact-checked cannot pass the CCE-101 auto-merge gate. All budget-triggered cuts still leave the PR open for an operator to accept or retry.'
source_files:
  - CHANGELOG.md
  - scripts/orchestrator_runner.py
  - tests/orchestrator/test_time_budget_authoring.py
last_reviewed: '2026-07-07'
status: draft
---

# Orchestrator

`scripts/orchestrator_runner.py:run()` is the entry point for the nightly (and manual) docs-agent run. One invocation walks a fixed pipeline over the PRs merged since the last successful run:

1. **source-collector** — pulls merged PRs (and linked Jira issues) in `last_sha..head_sha`. The orchestrator clips out-of-window results itself (`_clip_prs_to_window`, `scripts/orchestrator_runner.py:512`) and re-orders the survivors oldest-first (`_order_prs_oldest_first`, `scripts/orchestrator_runner.py:355`) so a truncated run always advances the baseline to a contiguous prefix.
2. **pr-summarizer** — one dispatch per admitted PR, producing `doc_targets` (lens + page hint + action).
3. **page-author fan-out** — `doc_targets` are batched by `(lens, page_hint)` and one `page-author` dispatch authors or edits each batch's page.
4. **content-validator** — runs the Tier-1/2/3 lint set against every page the fan-out touched; `block`-severity failures are reverted (`git checkout HEAD --`) or deleted, not merged.
5. **fact-checker** (warn-only) — for every surviving page that cites a resolvable repo source, checks the cited claim against that source.
6. Deterministic site generators, source-drift (M), citation-drift (C1), and core-drift (C2) — best-effort, read-only/auto-fixing stages.
7. **gap-detector** — flags PRs that look like they need a spec/plan but have none.
8. What's-New composition and PR open/append.

Each stage's failures accumulate into `state["current_run"]["partial_reasons"]` via `add_partial()`. Most reasons are `info_only=True` (advisory; the run still counts as fully successful); a non-info reason flips `state["current_run"]["partial"] = True`, which the CCE-101 merge gate reads before deciding whether to auto-merge.

## Time budget enforcement (CCE-114)

The orchestrator runs under a hard 60-minute CI job timeout. `resolve_time_budget()` (`scripts/orchestrator_runner.py:339`) resolves a *soft* deadline — `run.time_budget_seconds` in config, or `DEFAULT_TIME_BUDGET_SECONDS = 2700` (45 minutes, `scripts/orchestrator_runner.py:310`) if unset. A value `<= 0` (including an explicit CLI override of `0`) means unlimited: `deadline` is `None` and no loop below ever trips.

Before CCE-114, that deadline was checked exactly once — at PR admission, which typically completes within the first few minutes of a run. Everything downstream of admission (most expensive: the page-author fan-out, at one Opus dispatch per doc-target batch) ran unbounded. Run `27263616736` is the incident that forced the fix: admission finished on schedule, ~20 page-author dispatches then ran past the 45-minute soft deadline, and the job was killed at the 60-minute hard limit with the entire run's work discarded — the sixth consecutive nightly to die this way.

CCE-114 adds the same deadline check to every fan-out loop after admission. Each loop's guard follows one of two postures:

- **At-least-one-progress** (admission, authoring): the check only fires when the loop index is `> 0`, so a budget too tight to do anything still makes forward progress on the first item rather than deferring everything.
- **Skip-outright** (fact-checker, gap-detector): these are advisory loops with no ordering dependency the next run needs to preserve, so once the deadline has passed the loop breaks immediately — no "do one more" allowance, because every post-deadline second increases the risk of hitting the hard kill.

| Loop | Guard location | Posture | Partial reason prefix |
|---|---|---|---|
| PR admission | `scripts/orchestrator_runner.py:1394` | at-least-one-progress | `time_budget_exceeded: admitted i/N PRs` |
| page-author fan-out | `scripts/orchestrator_runner.py:1474` | at-least-one-progress | `time_budget_exceeded: authored i/N page batches` |
| fact-checker | `scripts/orchestrator_runner.py:1671` | skip-outright | `time_budget_exceeded: fact-checked i/N pages` |
| gap-detector | `scripts/orchestrator_runner.py:1786` | skip-outright | `time_budget_exceeded: gap-checked i/N PRs` |

The fact-checker cut is the one behavior change worth calling out explicitly: every other advisory-stage failure in this file (`fact_checker_unavailable`, `source_map_failed`, `verify_citations_failed`, and the fact-checker's own per-page dispatch reasons) is logged `info_only=True` and never touches `partial`. The CCE-114 time-budget cut of the fact-checker loop does **not** use `info_only` — it flips `partial` like the admission and authoring cuts do. That's deliberate: a page whose fact-check was skipped because the run ran out of time is factually unverified, not verified-and-clean, and the CCE-101 auto-merge gate (`merge.policy: auto`, the default) requires a non-partial run with zero fact-checker warnings. Without this, a budget-cut run could still auto-merge pages nobody ever checked.

All four cuts leave the nightly PR open rather than failing the run — `run()` still returns `0`, the partial reasons surface in the PR body, and an operator can accept the truncated content or wait for the next run to pick up where this one deferred.

Tests: `tests/orchestrator/test_time_budget_authoring.py` pins one test per guard (`test_authoring_loop_truncates_after_budget`, `test_fact_checker_loop_skips_after_budget`, `test_gap_detector_loop_skips_after_budget`) plus `test_unlimited_budget_authors_all_targets`, which asserts `time_budget_seconds=0` authors every target and never flips `partial`.

## See also

- `docs/site-src/archive/2026-06-10-cce114-time-budget-fanout-enforcement.md` — the incident chain from CCE-109 (admission-only deadline) to CCE-114 (fan-out enforcement).
- CCE-101 merge gate (`CHANGELOG.md`) for the auto-merge eligibility this page's `partial` flag feeds into.
</content>

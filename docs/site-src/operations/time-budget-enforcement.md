---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: architecture
---

# Time-budget enforcement

The orchestrator enforces a soft time budget across every expensive phase of the nightly run. The default budget is 2,700 seconds (45 minutes), set at `scripts/orchestrator_runner.py:310` as `DEFAULT_TIME_BUDGET_SECONDS`. This is deliberately below the 60-minute GitHub Actions job hard limit so there is breathing room for the PR-open and auto-merge stages.

## How the deadline is resolved

`resolve_time_budget` (`scripts/orchestrator_runner.py:339`) picks a value in this order:

1. CLI `--time-budget-seconds` override (including explicit `0` for unlimited).
2. `run.time_budget_seconds` in the host's `.engineering-docs-agent/config.yml`.
3. `DEFAULT_TIME_BUDGET_SECONDS` (2,700 s).

A value of `0` or below means no budget. The orchestrator converts a positive budget to a monotonic deadline at startup (`scripts/orchestrator_runner.py:1227`):

```python
deadline = clock() + budget if budget > 0 else None
```

When `deadline` is `None`, every loop's guard is a no-op and the run is unlimited.

## Phase-by-phase guards

### PR admission

The admission loop checks the deadline before processing each PR after the first. The `i > 0` condition guarantees at least one PR makes forward progress even on an already-expired budget (`scripts/orchestrator_runner.py:1360`).

When the deadline trips, the orchestrator records a partial reason in the form:

```
time_budget_exceeded: admitted {i}/{len(prs)} PRs (budget {budget}s); deferring PR #{n} to next run
```

### Page-author fan-out

The authoring fan-out is the most expensive phase — one Claude dispatch per doc-target batch. Before PR #136, this loop never checked the deadline. Run `27263616736` (June 5–10, 2026) confirmed approximately 20 dispatches started after the soft deadline and were killed when the 60-minute hard limit fired.

The fix (`scripts/orchestrator_runner.py:1440`) mirrors the admission guard exactly, including the `i > 0` at-least-one-progress guarantee:

```python
if deadline is not None and i > 0 and clock() > deadline:
    add_partial(
        state,
        f"time_budget_exceeded: authored {i}/{len(per_target)} "
        f"page batches (budget {budget}s); deferring the rest",
    )
    break
```

At least one page batch always runs, even if the clock was already past the deadline when this loop started.

### Fact-checker loop

The fact-checker loop dispatches one `fact-checker` agent per authored page that cites at least one resolvable repo source. This loop has **no at-least-one guarantee** — when the deadline has passed it skips outright (`scripts/orchestrator_runner.py:1610`):

```python
if deadline is not None and clock() > deadline:
    add_partial(
        state,
        f"time_budget_exceeded: fact-checked {i}/{len(fact_pages)} pages "
        f"(budget {budget}s); skipping the rest",
    )
    break
```

Every second past the deadline risks the hard kill. The partial reason from a skipped fact-checker is **not** `info_only`, so the CCE-101 auto-merge gate withholds merging the PR.

### Gap-detector loop

Same posture as the fact-checker: no at-least-one guarantee, skips outright when the deadline has passed (`scripts/orchestrator_runner.py:1725`). The partial reason format is:

```
time_budget_exceeded: gap-checked {i}/{len(prs)} PRs (budget {budget}s); skipping the rest
```

This also flips `partial: true` and blocks auto-merge.

## Effect on auto-merge (CCE-101)

Any `time_budget_exceeded` reason from the authoring, fact-checker, or gap-detector loop sets `partial: true` on the current run. The CCE-101 auto-merge gate (`scripts/orchestrator_runner.py:1901`) checks this flag and withholds the squash merge when it is set. The PR stays open; `state.json.last_successful_run` advances only when an operator merges it manually.

## Configuring the budget

Set a custom budget in the host's config file:

```yaml
run:
  time_budget_seconds: 3600   # 60 min — only safe if your job limit is higher
```

Set to `0` to disable budget enforcement entirely (not recommended for production):

```yaml
run:
  time_budget_seconds: 0
```

Pass `--time-budget-seconds 0` on the CLI for a one-off unlimited run without touching config.

## Test coverage

Four tests in `tests/orchestrator/test_time_budget_authoring.py` cover the CCE-114 guards using an injected `now_monotonic` clock:

- `test_authoring_loop_truncates_after_budget` — confirms `partial: true` and that only the first batch is authored when the clock trips at batch 1.
- `test_fact_checker_loop_skips_after_budget` — confirms all three pages are authored before the fact-checker gate fires, and `partial: true` is set.
- `test_gap_detector_loop_skips_after_budget` — confirms fact-checking completes and only the gap-detector is cut.
- `test_unlimited_budget_authors_all_targets` — confirms `time_budget_seconds=0` authors all three targets with no partial flag.

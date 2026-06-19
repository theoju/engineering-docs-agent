---
status: draft
sources:
- https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
---

# Nightly run time budget

The nightly runner enforces a soft time budget to stay inside the 60-minute GitHub Actions job hard kill. Every phase that dispatches subagents checks this deadline before starting a new dispatch. When the deadline passes, the run stops cleanly, marks the run partial, and lets the next nightly pick up where this one left off.

## Default budget

The default budget is **2700 seconds (45 minutes)**, defined at `scripts/orchestrator_runner.py:310`:

```python
DEFAULT_TIME_BUDGET_SECONDS = 2700  # 45 min; below the 60-min job hard limit
```

This leaves a 15-minute buffer below the hard kill for PR creation, the merge-gate check polls, and any overhead between phases.

## Overriding the budget

Set `run.time_budget_seconds` in `.engineering-docs-agent/config.yml` to change the budget for your host:

```yaml
run:
  time_budget_seconds: 3000
```

Pass `--time-budget-seconds 0` on the CLI to disable the budget entirely (unlimited). The runner converts any value ≤ 0 to `deadline=None`, which skips all budget checks. Never disable the budget in a CI environment with a hard job timeout.

## How the deadline is set

The runner records `deadline = clock() + budget` once at startup (`orchestrator_runner.py:1227`). `clock()` is `time.monotonic` in production — it is injected in tests so the full budget logic is exercisable without wall-clock waits. All phase checks compare `clock()` against this single deadline for the entire run.

## What each phase checks

### PR admission

Before summarizing each PR, the admission loop checks the deadline (`orchestrator_runner.py:1360`):

```python
if deadline is not None and i > 0 and clock() > deadline:
```

The `i > 0` guard ensures at least one PR is always processed, even if the deadline has already passed at loop start. When the budget is exceeded, the orchestrator truncates the PR list, records a `time_budget_exceeded` partial reason, and stops admitting. The cursor advances only to the last admitted PR, so deferred PRs are picked up next run.

### Page-author fan-out (CCE-114)

Before dispatching each `page-author` subagent, the fan-out loop checks the deadline (`orchestrator_runner.py:1440`):

```python
if deadline is not None and i > 0 and clock() > deadline:
    add_partial(
        state,
        f"time_budget_exceeded: authored {i}/{len(per_target)} "
        f"page batches (budget {budget}s); deferring the rest",
    )
    break
```

This check was the missing piece before PR #136 (CCE-114). Fan-out is the most expensive phase: a batch of 7 PRs can produce 40+ page-author dispatches. Without a budget check in this loop, the runner dispatched straight through the deadline. Because the job was killed before `state.json` could advance, the next nightly inherited an even larger window, compounding the problem. Six consecutive scheduled runs (June 5–10) failed this way.

The `i > 0` guarantee is the same as PR admission: at least one page is always authored.

### Fact-checker loop (CCE-114)

After authoring, the fact-checker checks the deadline before each page (`orchestrator_runner.py:1610`). Unlike the fan-out, there is no `i > 0` guarantee here — the check fires on the very first page. If the deadline is already past when fact-checking begins, the entire fact-check phase is skipped and a `time_budget_exceeded` partial reason is recorded. Pages that skip fact-checking must not auto-merge: the partial flag blocks the CCE-101 auto-merge gate.

## Budget consumption by the merge gate

The CCE-101 merge gate also consumes time from the same run clock:

| Setting | Default |
|---|---|
| `checks_grace_seconds` | 120 s |
| `checks_timeout_seconds` | 900 s |

In the worst case the merge gate waits up to 1020 seconds (17 minutes). With the 45-minute budget this leaves roughly 28 minutes for all authoring phases. Configure your host's merge settings (`merge.checks_grace_seconds`, `merge.checks_timeout_seconds`) if you need more headroom for authoring on large windows.

## Reading partial reasons

When the budget is exceeded, `state.json` and the PR body both carry a `partial_reasons` entry. Look for `time_budget_exceeded:` entries. Each entry names the phase and how many units were completed versus total:

```
time_budget_exceeded: authored 12/43 page batches (budget 2700s); deferring the rest
```

A run that hits the budget in fan-out will still open a PR with the pages it finished. The next nightly processes the remaining PRs in the same window, advancing the cursor by the end of the new run's admitted set.

## Disabling vs. tuning

Do not disable the budget in CI unless you have no job hard limit and can guarantee the runner will not accumulate unbounded windows. Tuning is almost always safer: reduce the per-lens page count, increase `run.time_budget_seconds`, or spread large PR batches across days by merging more frequently.

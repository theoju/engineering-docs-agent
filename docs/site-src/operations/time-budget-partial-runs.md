---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: architecture
---

# Time budget and partial runs

The orchestrator enforces a soft time budget so nightly runs complete and
produce a PR rather than being killed by the workflow's hard 60-minute limit.
This page explains the budget, where it is enforced, what a partial run looks
like, and what happens next.

## The budget

The default budget is **2 700 seconds (45 minutes)**, set at
`orchestrator_runner.py:310`:

```python
DEFAULT_TIME_BUDGET_SECONDS = 2700  # 45 min; below the 60-min job hard limit
```

You can override it in your host config:

```yaml
run:
  time_budget_seconds: 1800   # 30 min
```

Pass `0` (or a negative value) to run with no budget — the orchestrator sets
`deadline = None` and skips every guard. Useful for local debugging; never
appropriate for scheduled runs.

The deadline is a monotonic clock value: `deadline = clock() + budget` at
`run()` entry (`orchestrator_runner.py:1227`). All guards compare
`clock() > deadline`.

## What CCE-114 fixed

CCE-109 added a deadline check at PR admission, but admission finishes in the
first few minutes of a run. The page-author fan-out — one Claude dispatch per
doc-target batch, potentially dozens — ran completely unbounded. Run
27263616736 admitted all PRs within budget and then authored straight through
the deadline into the workflow's 60-minute hard kill. Six consecutive
scheduled nightlies (2026-06-05 through 2026-06-10) were killed this way,
producing no PR and no state advance.

CCE-114 (PR #136) added deadline guards inside the three post-admission loops.

## Enforcement points

### Authoring fan-out (CCE-114)

`orchestrator_runner.py:1440`:

```python
if deadline is not None and i > 0 and clock() > deadline:
    add_partial(
        state,
        f"time_budget_exceeded: authored {i}/{len(per_target)} "
        f"page batches (budget {budget}s); deferring the rest",
    )
    break
```

The `i > 0` guard ensures at least one batch always completes, mirroring the
PR-admission guarantee. Remaining targets are not discarded — they re-enter
the queue on the next run when their source files change again.

### Fact-checker loop (CCE-114)

`orchestrator_runner.py:1610`:

```python
if deadline is not None and clock() > deadline:
    add_partial(
        state,
        f"time_budget_exceeded: fact-checked {i}/{len(fact_pages)} pages "
        f"(budget {budget}s); skipping the rest",
    )
    break
```

No at-least-one guarantee here — the fact-checker is an advisory warn layer.
The partial reason is **not** `info_only`, so the CCE-101 merge gate sees it
and refuses auto-merge. Pages that were never fact-checked must not land
without human review.

### Gap-detector loop (CCE-114)

`orchestrator_runner.py:1725`:

```python
if deadline is not None and clock() > deadline:
    add_partial(
        state,
        f"time_budget_exceeded: gap-checked {i}/{len(prs)} PRs "
        f"(budget {budget}s); skipping the rest",
    )
    break
```

Same posture as the fact-checker: no at-least-one, and the partial reason
blocks auto-merge.

## What a partial run produces

When any deadline guard trips, `state["current_run"]["partial"]` is `True` and
`partial_reasons` contains at least one `time_budget_exceeded: …` entry. The
run continues to lint surviving authored pages, opens the docs-agent PR with
`partial: true` in the body, and records the partial reasons there so the
operator sees the cut without opening `state.json`.

Partial PRs never auto-merge (`orchestrator_runner.py:1862` checks
`state["current_run"]["partial"]`). They stay open until the operator merges
or a subsequent full run supersedes them via the D2 auto-close sweep.

## Baseline advance on a truncated run

When the authoring cut fires, the orchestrator applies CCE-109 Component 4
invariants before advancing `last_successful_run.head_sha`:

- Advances only to the merge SHA of the **last admitted PR** (not to HEAD).
- Refuses advance when no admitted PR has a usable `merge_sha`, or when a
  deferred PR has no `merge_sha` and would be stranded behind the cursor, or
  when the cursor SHA is not resolvable in the repo.
- Records `window_head_sha` in `last_successful_run` so the CCE-43 same-hour
  rerun guard recognises the window as already processed.

Each refusal records a specific partial reason (e.g.,
`time_budget_no_advance_no_cursor`, `time_budget_advance_out_of_window`) so
you can distinguish a safe baseline hold from a data problem.

## Deferred targets

Page batches deferred by the authoring cut re-enter the queue on the next run
when the source files they depend on appear in the new window. There is no
explicit retry queue — the source change is the re-entry signal.

## Tests

`tests/orchestrator/test_time_budget_authoring.py` pins all three guards with
an injected monotonic clock. Key cases:

| Test | What it pins |
|---|---|
| `test_authoring_loop_truncates_after_budget` | First batch authors; second and third are cut; partial reason contains `authored 1/3 page batches`. |
| `test_fact_checker_loop_skips_after_budget` | All three batches author; fact-checker first gate fires; partial reason contains `fact-checked 0/3 pages`. |
| `test_gap_detector_loop_skips_after_budget` | Authoring and fact-checker pass; gap-detector first gate fires. |
| `test_unlimited_budget_authors_all_targets` | `time_budget_seconds=0` → `deadline=None` → all three batches author, `partial` is `False`. |

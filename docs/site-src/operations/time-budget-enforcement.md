---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: architecture
---

# Time-budget enforcement

The orchestrator runs inside a GitHub Actions job with a hard 60-minute kill. The CCE-109 soft budget — defaulting to 2700 seconds (45 minutes) — gives the orchestrator a chance to finish gracefully before the hard kill fires. Without active enforcement, a large backlog window can consume the entire budget in the page-author fan-out phase alone, leaving the job cancelled mid-run with no PR opened and no baseline advanced.

## The budget and deadline

At startup, the orchestrator computes a monotonic deadline (`orchestrator_runner.py:1227`):

```python
deadline = clock() + budget if budget > 0 else None
```

When `deadline` is `None` (budget = 0), all deadline guards are bypassed and the run is unbounded.

The budget is set by `run.time_budget_seconds` in config, or by `--time-budget-seconds` on the CLI. The default is 2700 seconds. Set it to `0` only in test environments or when you have confirmed the run cannot be cancelled.

## Which phases are deadline-guarded

Four loops check the deadline before each unit of work:

| Phase | Guard location | At-least-one guarantee | Sets partial? |
|---|---|---|---|
| PR summarization | `orchestrator_runner.py:1360` | Yes (`i > 0`) | Yes |
| Page-author fan-out | `orchestrator_runner.py:1440` | Yes (`i > 0`) | Yes |
| Fact-checker loop | `orchestrator_runner.py` | No | Yes |
| Gap-detector loop | `orchestrator_runner.py:1725` | No | Yes |

The summarization and page-author loops guarantee that at least one item completes before the deadline can halt further work. The fact-checker and gap-detector have no such guarantee — every second past the deadline risks the hard kill, so they are skipped outright once the budget is exhausted.

## The doom-loop failure mode

Before PR #136, the deadline was only checked at PR admission (summarization) and the auto-merge gate. The page-author fan-out, fact-checker, and gap-detector ran completely unbounded.

In a 7-PR backlog window, the page-author fan-out alone dispatches up to 43 Opus calls — one per `(lens, page_hint)` batch. Six consecutive scheduled nightlies (2026-06-05 through 2026-06-10) hit the 60-minute hard kill mid-fan-out. Each cancelled run produced no PR and advanced no baseline. The unprocessed window grew by one day every night, adding another PR to the next run's batch. The cycle was self-reinforcing: it could not heal without outside intervention.

PR #136 closed the loop by inserting deadline guards into the page-author fan-out and the fact-checker and gap-detector passes.

## Partial runs and the auto-merge gate

Any deadline trigger sets `partial=true` on the run. The orchestrator records this in `current_run` and in the PR body.

The CCE-101 auto-merge gate enforces: **eligible = non-partial AND zero fact-checker warnings AND no human commits on the PR**. A partial PR stays open for operator review. Pages that were never fact-checked or gap-checked must not land silently.

When you see a partial PR caused by time truncation, you have two options:

- **Merge the PR** to accept the coverage gap and advance the baseline. The next nightly runs against a smaller window and is more likely to complete within budget.
- **Wait for the next nightly** to retry. The window shrinks only once a baseline-advancing merge lands, so unmerged partial PRs do not reduce the next run's load.

`state.json.last_successful_run` advances only when a PR merges. The D2 auto-close sweep supersedes stale PRs once the baseline advances past them.

## Config reference

```yaml
run:
  time_budget_seconds: 2700   # default; 0 = unlimited

merge:
  policy: auto                 # default; set to "manual" to opt out
  checks_grace_seconds: 120    # grace before checking CI
  checks_timeout_seconds: 900  # max wait for CI to settle
```

Both `checks_grace_seconds` and `checks_timeout_seconds` are bounded by the run deadline — the auto-merge gate does not run past the budget.

## Baseline advancement on a truncated run

When the page-author fan-out is halted mid-batch, the orchestrator advances the baseline only to the cursor of the last fully admitted PR — not to `head_sha`. This invariant is enforced at `orchestrator_runner.py:1793`. The next nightly picks up from that cursor, not from scratch.

## Test coverage

PR #136 added four TDD tests covering:

1. Authoring truncation with on-disk file verification (confirms written files are not rolled back on timeout)
2. Fact-checker skip when budget is exhausted at fact-check phase entry
3. Gap-detector skip when budget is exhausted at gap-detect phase entry
4. Unlimited-budget passthrough (budget = 0 bypasses all guards)

Full suite at merge: 1063 passed, 3 skipped.

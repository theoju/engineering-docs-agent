---
description: 'Documents the nightly orchestrator run loop: source collection, PR admission, the page-author fan-out, and the advisory fact-checker/gap-detector passes, plus the CCE-109/CCE-114 time-budget enforcement that bounds all four phases.'
source_files:
  - scripts/orchestrator_runner.py
  - tests/orchestrator/test_time_budget_authoring.py
last_reviewed: '2026-07-05'
status: draft
doc_kind: architecture
---

# Orchestrator run loop

`scripts/orchestrator_runner.py:run()` drives one nightly window end to end: collect sources, admit PRs, author pages, validate and fact-check them, detect gaps, then write the What's New entry and (depending on `merge:` policy) open or auto-merge the PR. Each phase is a loop over a list — PRs, doc-target batches, authored pages — and each of those loops now enforces the same soft time budget.

## The soft deadline

`resolve_time_budget` (`scripts/orchestrator_runner.py:339`) resolves the budget: CLI override first, then `run.time_budget_seconds` in config, then `DEFAULT_TIME_BUDGET_SECONDS` (2700s / 45 minutes — deliberately below the workflow's `timeout-minutes: 60` hard kill). A budget `<= 0` means unlimited; `run()` turns that into `deadline = None` (`scripts/orchestrator_runner.py:1259-1261`) and every gate below becomes a no-op.

With a real budget, `deadline = clock() + budget` is computed once at the top of `run()`, using an injectable `now_monotonic` clock (production uses `time.monotonic`; tests inject a fake sequence via `_fake_clock`).

## Why every expensive loop checks it (CCE-114)

CCE-109 originally gated only PR *admission* on this deadline. That check completes minutes into a run — admission is comparatively cheap — so the phases after it ran unbounded. The most expensive phase, the page-author fan-out (one Claude dispatch per doc-target batch, up to ~50 dispatches in a big window), then blew straight through the deadline into the workflow's 60-minute hard kill. Six consecutive scheduled nightlies (June 5–10) died this way: each run discarded roughly an hour of Opus dispatch work, opened no PR, and advanced no state — the exact doom loop CCE-109 was supposed to close. Forensics on run 27263616736 found ~20 of 43 page-author dispatches had started *after* the deadline had already passed.

The fix adds a deadline check inside each of the three loops that follow admission. They don't all fail the same way, on purpose:

| Loop | Guard location | Posture | Effect |
|---|---|---|---|
| PR admission | `scripts/orchestrator_runner.py:1393-1409` | at-least-one-progress (`i > 0`) | truncates `prs` to the admitted prefix; deferred PRs retry next run |
| Page-author fan-out | `scripts/orchestrator_runner.py:1474-1480` | at-least-one-progress (`i > 0`) | breaks out of the batch loop; remaining doc targets are simply not authored this run |
| Fact-checker (warn layer) | `scripts/orchestrator_runner.py:1671-1678` | skip outright, no minimum | breaks immediately, even on the very first page |
| Gap-detector | `scripts/orchestrator_runner.py:1786-1792` | skip outright, no minimum | breaks immediately, even on the very first PR |

Admission and authoring keep the "at least one" guarantee — `i > 0` means the gate never fires before the first item, so a run always makes forward progress even on a razor-thin budget. Fact-checking and gap detection don't get that guarantee: they're advisory passes over content that already exists, so skipping the *entire* remaining layer costs nothing structural, and every extra second spent past the deadline is pure risk against the hard kill.

## Partial, not silent

Every one of these truncations calls `add_partial(state, ...)` with a `time_budget_exceeded: ...` reason and — critically — none of them pass `info_only=True`. That's deliberate for the fact-checker and gap-detector cases in particular: an authored page that was *never* fact-checked must not be indistinguishable from one that passed. The CCE-101 auto-merge gate keys directly off `partial`, so a time-budget cut in any of these four loops leaves the docs-agent PR open for the operator to accept the coverage loss or rerun the window — it can never silently auto-merge un-checked content.

The reason strings are counted, not just flagged, so operators can see exactly how much was cut:

```
time_budget_exceeded: authored 1/3 page batches (budget 100s); deferring the rest
time_budget_exceeded: fact-checked 0/3 pages (budget 100s); skipping the rest
time_budget_exceeded: gap-checked 0/3 PRs (budget 100s); skipping the rest
```

`tests/orchestrator/test_time_budget_authoring.py` pins all three cuts plus the unlimited-budget (`time_budget_seconds=0`) case, which asserts `partial is False` and every doc target still gets authored — confirming the gates are true no-ops when there's no budget to blow.

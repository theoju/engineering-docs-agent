---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# CCE-114: Time-budget enforcement extended to authoring, fact-checker, and gap-detector loops

**Date:** 2026-06-10
**Tracker:** CCE-114
**PR:** [#136](https://github.com/theoju/engineering-docs-agent/pull/136)

## Context

CCE-109 introduced a 45-minute soft deadline (`DEFAULT_TIME_BUDGET_SECONDS = 2700`, `scripts/orchestrator_runner.py:310`) to prevent nightly runs from overrunning the 60-minute GitHub Actions job limit. The deadline was checked once between PR admissions — at the top of the `for i, pr in enumerate(prs)` loop (`orchestrator_runner.py:1360`).

That guard completed in the first few minutes of each run. Every subsequent phase — the page-author fan-out, the fact-checker loop, and the gap-detector loop — ran unbounded.

## Forensic evidence

Six consecutive nightly runs (June 5–10 2026) were killed at the 60-minute hard limit. Run `27263616736` is the forensic anchor. A 7-PR backlog window caused roughly 20 page-author dispatches to start well after the 45-minute soft deadline. Each page-author call is one full Opus dispatch; at ~1–3 minutes per dispatch, the fan-out easily consumed the remaining margin. The workflow killed the process, `state.json.last_successful_run` never advanced, and the same 7-PR window was retried the following night — the doom loop CCE-109 was meant to break.

The root cause: PR admission is fast. All PRs in the window were admitted within the first few minutes. The expensive work starts after admission ends. CCE-109 guarded only the cheap phase.

## Decision

Extend deadline enforcement to every post-admission loop. Three guards were added in PR #136.

### 1. Authoring fan-out (`orchestrator_runner.py:1440`)

Before each `(lens, page_hint)` batch in the `per_target` loop, the runner now checks:

```python
if deadline is not None and i > 0 and clock() > deadline:
    add_partial(state, f"time_budget_exceeded: authored {i}/{len(per_target)} "
                       f"page batches (budget {budget}s); deferring the rest")
    break
```

The `i > 0` guard preserves the at-least-one-progress invariant: even on a tight budget, the first batch always dispatches. This mirrors the identical guard on PR admission and ensures the cursor can advance.

A deadline hit here sets `partial = True`, which the CCE-101 auto-merge gate rejects. The PR opens with the authored pages; the operator decides whether to accept partial coverage or let the next nightly retry the remaining targets.

### 2. Fact-checker loop (`orchestrator_runner.py:1610`)

Before each per-page fact-checker dispatch:

```python
if deadline is not None and clock() > deadline:
    add_partial(state, f"time_budget_exceeded: fact-checked {i}/{len(fact_pages)} "
                       f"pages (budget {budget}s); skipping the rest")
    break
```

No at-least-one guarantee here. The fact-checker is advisory (warn-only findings), but a page that was never fact-checked must not auto-merge. Every second past the deadline risks the 60-minute hard kill, so the loop exits immediately on expiry. The resulting `partial` flag blocks auto-merge via CCE-101.

The comment in the source (`orchestrator_runner.py:1605`) notes that this reason is deliberately **not** `info_only` — unlike other advisory-layer partial reasons, fact-check incompleteness is a hard gate for auto-merge eligibility.

### 3. Gap-detector loop (`orchestrator_runner.py:1725`)

Before each per-PR gap-detector dispatch:

```python
if deadline is not None and clock() > deadline:
    add_partial(state, f"time_budget_exceeded: gap-checked {i}/{len(prs)} PRs "
                       f"(budget {budget}s); skipping the rest")
    break
```

Same posture as the fact-checker: skip outright, set `partial`, block auto-merge.

## Partial PR posture

Any run that hits the deadline in any of the three new guards produces a PR with `partial: true` in its body. The CCE-101 auto-merge gate rejects partial PRs unconditionally. The operator can:

- Merge the partial PR manually to accept the current coverage, then let the next nightly fill in the rest.
- Leave it open; the D2 freshest-only sweep will close it when the next nightly opens a successor PR.

The cursor advance logic (CCE-109 Component 4) is unaffected: an authoring-loop cut does not change which PRs were admitted, so the baseline still advances to the last admitted PR's merge SHA (subject to the existing unanchored-deferred guard).

## Test coverage

`tests/orchestrator/test_time_budget_authoring.py` pins all three guards with four pytest cases:

- `test_authoring_loop_truncates_after_budget` — confirms batch 0 is authored, batches 1–2 are skipped, and `partial` is set.
- `test_fact_checker_loop_skips_after_budget` — confirms all 3 pages are authored (authoring inside budget), then the fact-checker skips immediately on expiry.
- `test_gap_detector_loop_skips_after_budget` — confirms all 3 pages are authored and fact-checked (no dispatches in dry-run; pages cite nothing), then gap detection skips on expiry.
- `test_unlimited_budget_authors_all_targets` — confirms that `time_budget_seconds=0` (unlimited) authors all targets with no `time_budget_exceeded` reasons.

The fake clock (`_fake_clock`) in the test module injects monotonic values in order, letting tests trigger each guard boundary precisely without wall-clock sleeps.

## Enforcement coverage after this PR

| Phase | Deadline check | At-least-one |
|---|---|---|
| PR admission | `orchestrator_runner.py:1360` (CCE-109) | Yes (`i > 0`) |
| Authoring fan-out | `orchestrator_runner.py:1440` (CCE-114) | Yes (`i > 0`) |
| Fact-checker | `orchestrator_runner.py:1610` (CCE-114) | No (skip outright) |
| Gap-detector | `orchestrator_runner.py:1725` (CCE-114) | No (skip outright) |
| Merge-gate polling | bounded by `checks_timeout_seconds` (CCE-109) | N/A |

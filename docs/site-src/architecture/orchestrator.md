---
description: 'Documents the nightly docs-agent orchestrator: PR admission, the page-author fan-out, and the advisory fact-checker/gap-detector loops, plus the CCE-109/CCE-114 soft time budget that bounds all four.'
source_files:
  - CHANGELOG.md
  - scripts/orchestrator_runner.py
  - tests/orchestrator/test_time_budget_authoring.py
last_reviewed: '2026-07-09'
status: draft
doc_kind: architecture
---

# Orchestrator: nightly run architecture

`scripts/orchestrator_runner.py:run()` is the entry point for the nightly `docs-agent-nightly.yml` workflow. One invocation processes one review window — the commit range between `state.json`'s `last_successful_run.head_sha` and the current `HEAD` — through four sequential, dispatch-heavy loops: PR admission, page-author fan-out, an advisory fact-checker pass, and an advisory gap-detector pass. All four share one soft deadline.

## The soft time budget

`resolve_time_budget()` (`scripts/orchestrator_runner.py:339`) resolves a per-run budget in seconds: CLI override, then `run.time_budget_seconds` from host config, then `DEFAULT_TIME_BUDGET_SECONDS = 2700` (45 minutes — chosen to sit under the workflow's 60-minute hard kill). A budget `<= 0` means unlimited; `run()` turns that into `deadline = None` and every loop below runs to completion.

You'll see the same two-line guard shape at the top of each loop:

```python
if deadline is not None and i > 0 and clock() > deadline:
    add_partial(state, "time_budget_exceeded: ...")
    break
```

The `i > 0` clause is the **at-least-one-progress guarantee**: even a run that starts already over budget still admits one PR and authors one page batch before any loop gives up. Without it, a pathologically tight budget could produce a PR with zero content and no clear signal why.

## Why this exists: the doom loop

Before CCE-114, the deadline was checked only between PR admissions (CCE-109) and again at the merge gate. Admission is cheap and finishes minutes into a run, so it never actually bounded anything — the page-author fan-out, the most expensive phase at up to ~50 Opus dispatches per run, then ran unbounded straight through the deadline into the workflow's 60-minute hard kill, and everything the run had done was discarded.

Forensics on run `27263616736` found ~20 of 43 page-author dispatches starting *after* the 09:15:39 deadline had already passed. That run was the sixth consecutive scheduled nightly (June 5–10) to die this way — each one burning roughly an hour of compute with no PR opened and no state advance.

CCE-114 closes the gap by pushing the same deadline check inside all three of the expensive per-run loops, not just admission.

## Loop 1: PR admission

`scripts/orchestrator_runner.py:1394` gates the `pr-summarizer` dispatch loop. On trip, it truncates `prs` to the already-admitted prefix and records:

```
time_budget_exceeded: admitted {i}/{len(prs)} PRs (budget {budget}s); deferring PR #{n} to next run
```

Because PRs are pre-sorted oldest-first (`_order_prs_oldest_first`), a truncated prefix is always a contiguous oldest run — the state-advance logic that follows never strands an older, un-admitted PR behind a newer one it skipped.

## Loop 2: page-author fan-out

This is the phase CCE-114 was written for. `doc_targets` from every admitted PR's summary are batched by `(lens, page_hint)` before dispatch, so one `page-author` call can cover several PRs that touch the same page. The guard sits at `scripts/orchestrator_runner.py:1474`, immediately inside the `for i, ((lens, hint), batch_summaries) in enumerate(per_target.items())` loop, before any per-batch work (path resolution, frontmatter construction, the dispatch itself) happens:

```
time_budget_exceeded: authored {i}/{len(per_target)} page batches (budget {budget}s); deferring the rest
```

Same at-least-one-progress rule as admission: batch 0 always dispatches regardless of how late the clock already is; batch 1 onward is gated. `tests/orchestrator/test_time_budget_authoring.py::test_authoring_loop_truncates_after_budget` pins this with a three-target batch (`alpha`/`beta`/`gamma`) and a fake clock that trips before batch 1 — `alpha.md` is written, `beta.md` and `gamma.md` are not, and the run's `partial` flag is `True`.

## Loop 3: fact-checker (warn layer)

The fact-checker is advisory by design — a `contradiction` verdict becomes a PR-body warning, never a reason to drop a page. But CCE-114 makes the *time-budget cut itself* an exception to that rule. The guard at `scripts/orchestrator_runner.py:1671` sits inside the per-page loop over `fact_pages` (authored pages that survived lint and cite at least one resolvable repo source):

```
time_budget_exceeded: fact-checked {i}/{len(fact_pages)} pages (budget {budget}s); skipping the rest
```

Unlike the admission and authoring guards, this one has **no** `i > 0` exemption — it can skip the entire loop, including page 0. That's deliberate: this reason is *not* `info_only`. A page that was never fact-checked must not be treated as verified, and the CCE-101 auto-merge gate keys directly off the run's `partial` flag. Marking the run partial here is what stops an unchecked page from slipping through auto-merge. `test_fact_checker_loop_skips_after_budget` confirms authoring itself is unaffected — `gamma.md` still exists on disk — only the fact-check pass is skipped.

## Loop 4: gap-detector (warn layer)

Same posture as the fact-checker: the guard at `scripts/orchestrator_runner.py:1786` sits inside the per-PR loop over `prs` and can skip from the first iteration. On trip:

```
time_budget_exceeded: gap-checked {i}/{len(prs)} PRs (budget {budget}s); skipping the rest
```

`test_gap_detector_loop_skips_after_budget` runs the clock past the fact-checker loop's per-page gates first (proving that loop completed cleanly), then trips the gap-detector's first gate — the assertion checks that a `fact-checked` reason is *absent* from `partial_reasons`, confirming the two loops are independently gated rather than sharing one flag.

## What happens after a cut

None of the four guards abort the run. Every cut `break`s out of its own loop and falls through to the rest of `run()` — lint, the deterministic site generators, source/citation drift, and PR open-or-append. A time-budget-truncated run still opens (or updates) its `docs-agent/YYYY-MM-DD` PR; it just does so with `partial: true` and a `time_budget_exceeded: ...` entry in `partial_reasons`, both of which the PR body renders. Per CCE-101, a partial run is never auto-merge-eligible — the PR sits open for an operator to accept the coverage loss (merge as-is) or let the next scheduled window pick up the deferred work.

`test_unlimited_budget_authors_all_targets` is the control case: `time_budget_seconds=0` resolves to `deadline=None`, all three `alpha`/`beta`/`gamma` targets get authored, and `partial` stays `False`.

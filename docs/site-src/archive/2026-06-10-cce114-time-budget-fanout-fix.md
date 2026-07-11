---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# CCE-114: the authoring fan-out ignored the CCE-109 time budget

CCE-109's soft deadline only gated PR admission; the page-author fan-out ran unbounded past it, and six nightlies died at the workflow's 60-minute hard kill.

## What happened

CCE-109 added a soft time budget to the nightly run: compute a monotonic `deadline = clock() + budget` once at the top of `run()` (`scripts/orchestrator_runner.py:1261`), then check it before admitting each PR (`scripts/orchestrator_runner.py:1394`), truncating admission with an `at-least-one-progress` guarantee (`i > 0`) so a run always makes forward movement even when the very first check already trips.

That guard covered admission only. Page authoring — one Claude dispatch per `(lens, page_hint)` batch, the single most expensive phase of a run — never consulted the deadline at all. A run with a large PR window admitted everything within budget (admission completes minutes in) and then authored straight through the deadline into the workflow's 60-minute hard kill, discarding all in-flight work. Run `27263616736` is the pinned repro: roughly 20 page-author dispatches started after the deadline had already passed.

## The fix

`scripts/orchestrator_runner.py:1467-1480` adds the same `at-least-one-progress` deadline check to the authoring loop, keyed off batch index `i` instead of PR index: batch 0 always dispatches, batch 1+ checks `clock() > deadline` first and breaks with a `time_budget_exceeded: authored {i}/{len(per_target)} page batches` partial reason if it has tripped.

The two advisory loops downstream of authoring — fact-checker (`scripts/orchestrator_runner.py:1664-1678`) and gap-detector (`scripts/orchestrator_runner.py:1784` onward) — get a stricter posture: skip outright on the first post-deadline check, no at-least-one exception. Both loops record a `time_budget_exceeded: ...` partial reason and flip the run to `partial`, deliberately **not** `info_only`, even though the rest of what those loops do (fact-check warnings, gap flags) is otherwise advisory. A page that was cut mid-authoring, or authored but never fact-checked, must not slip through the CCE-101 auto-merge gate — that gate keys directly off `partial`.

`tests/orchestrator/test_time_budget_authoring.py` pins all three loop guards plus the `time_budget_seconds=0` (unlimited) escape hatch, using a fake monotonic clock (`_fake_clock`) that returns a scripted sequence of values so each test controls exactly which check trips.

## Why the fact-checker and gap-detector loops skip outright instead of at-least-one

Admission and authoring both guarantee at least one unit of progress per run even if the deadline has already passed by the first check — otherwise a persistently tight budget could starve the run entirely. Fact-checking and gap-detection don't get that guarantee: they run after authoring has already consumed the bulk of the budget, so every second spent past the deadline is pure downside risk against the workflow's hard kill, with no corresponding "make forward progress" argument (the pages are already on disk either way). Skipping the whole layer is safe precisely because both are warn-only capabilities to begin with — cutting a warning is cheaper than truncating content.

## References

- `scripts/orchestrator_runner.py:1261` — deadline computed once, or `None` for the unlimited case.
- `scripts/orchestrator_runner.py:1394` and `scripts/orchestrator_runner.py:1467-1480` — the two at-least-one-progress guards (admission, authoring).
- `scripts/orchestrator_runner.py:1664-1678` and `scripts/orchestrator_runner.py:1784` — the two skip-outright guards (fact-checker, gap-detector).
- `tests/orchestrator/test_time_budget_authoring.py` — regression coverage for all four loop behaviors.
- `CHANGELOG.md` — "CCE-109 time budget now bounds the authoring fan-out (CCE-114)" under Unreleased/Fixed.
- CCE-109 (original soft-deadline design, admission-only) and CCE-101 (the merge gate that keys off `partial`).

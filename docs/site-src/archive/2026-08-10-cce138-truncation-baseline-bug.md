---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/211
synthesized_into: []
doc_kind: decision
---

# CCE-138: Authoring-Loop Truncation Silently Advanced the Baseline to Full Window HEAD

An authoring-truncated nightly run persisted a baseline claiming coverage of the whole review window even when it had written only one of several page batches — because the authoring loop's time-budget break never set the flag the promotion block needed to route it onto the safe path.

## Symptom

On the `advanced-data-import-system` host, every one of the ten docs-agent PRs merged between 2026-06-26 and 2026-07-25 advanced `state.json`'s baseline to the full window HEAD, regardless of how many page batches the run actually authored before it ran out of time budget. The un-authored batches were dropped — permanently, since the next run's `last_sha..head_sha` window no longer covered the PRs they belonged to — while the PR body reported the full window as covered. Nothing errored. The gap was invisible in CI and invisible in the PR diff; it only showed up as pages that were promised and never appeared.

## Root cause

`orchestrator_runner.run` has two places that can truncate a run against the CCE-109 soft deadline: the PR-admission loop and the page-authoring loop. Both stop early and record a `time_budget_exceeded` partial reason. Only the admission loop also set a local `time_truncated = True`. The authoring loop's break — added later, by CCE-114, for the identical reason — copied the deadline check and the partial-reason call but not the flag assignment.

`time_truncated` is read in exactly one place downstream: the state-promotion block that decides what `advance_sha` becomes. When the flag is `True`, the block computes a per-PR cursor (`_last_processed_merge_sha` → `_rev_parse_commit` → `_sha_in_window`) and refuses to advance at all if it can't prove the cursor is safe. When the flag is `False`, the block takes its `else` branch and writes `state["current_run"]["head_sha"]` — the full window HEAD — as the new baseline, unconditionally.

Because the admission loop always set the flag, that safe-advance machinery had existed since CCE-109 and worked correctly for admission truncation. But an authoring truncation left `time_truncated` at its default `False`, so it fell straight through to the `else` branch every time — the exact behavior a clean, non-truncated run is supposed to get. The guard was copied between the two loops; the one line that made the guard mean something was not, and an absent assignment produces no error. The consequence only surfaced later, in a different function, on merge — which is why it went undetected for a month across ten merged PRs.

## The fix

One line, at the authoring loop's existing time-budget break in `orchestrator_runner.run`:

```
time_truncated = True
```

placed immediately before the `break`, mirroring the admission loop's assignment. No new state, no new config key, and no new refusal logic — the three CCE-109 refusal branches (no usable cursor; an unanchored deferred PR; a cursor that doesn't resolve inside the window) already existed and already worked; they were simply unreachable from the authoring path. This fix makes them reachable. Five lines changed in `scripts/orchestrator_runner.py` total (the assignment plus four explanatory comment lines).

## Verification

Five tests in `tests/orchestrator/test_authoring_truncation_advance.py` cover the authoring-truncation path end to end, each running `orchestrator_runner.run` against a real git fixture rather than asserting on internals directly:

- `tests/orchestrator/test_authoring_truncation_advance.py:test_authoring_truncation_advances_to_cursor_not_head` — the core case. Every fixture in the file places a non-PR commit on top of the newest PR-merge commit, so the cursor and `HEAD` are provably different shas; the test asserts `advance_sha != head_sha` as well as `advance_sha == cursor`. The negative assertion is deliberate — the bug was a fall-through to `HEAD`, so `advance == cursor` alone would pass vacuously on a fixture where the two happen to coincide.
- `tests/orchestrator/test_authoring_truncation_advance.py:test_authoring_truncation_without_cursor_holds_baseline` and `tests/orchestrator/test_authoring_truncation_advance.py:test_authoring_truncation_with_unresolvable_cursor_holds_baseline` — the two CCE-109 refusal branches that were previously dead code on this path, now exercised and confirmed to hold the prior baseline.
- `tests/orchestrator/test_authoring_truncation_advance.py:test_authoring_truncation_never_reports_unanchored_deferred` — pins the third refusal branch as correctly *silent* on a pure authoring truncation: it fires only for a PR the admission loop deferred, and an authoring truncation defers none (every admitted PR was processed by the time authoring cut off).
- `tests/orchestrator/test_authoring_truncation_advance.py:test_admission_truncation_advance_unchanged_by_track_a` — a regression guard, constructed to pass identically with and without the fix, pinning that admission-only truncation is untouched.

The first four were mutation-verified: deleting the `time_truncated = True` line makes all four fail, which is what confirms they exercise the fixed path rather than asserting something true by construction.

## What this does not fix

Under an authoring truncation the admission loop had already completed, so the cursor lands on the *newest admitted PR's* merge sha — even though page batches are keyed by `(lens, page_hint)`, not by PR, and the batch actually cut off by the deadline can carry summaries from any admitted PR, including the oldest. The fix stops the advance from reaching past every PR in the window; it does not yet guarantee the advance stops at the last PR whose page batches all landed. That gap was closed separately, by CCE-140's `advance_cursor_list`, which narrows the cursor walk to stop at the oldest PR still owed a page and — per the plan this fix shipped from — deliberately supersedes three of this fix's five tests (their assertions tighten from "advance equals the last processed PR" to "advance does not move past an unfinished one"). The discriminating `advance != head` assertion survives unchanged in every one of them.

## References

Design: `docs/superpowers/plans/2026-08-10-cce-138-cursor-honesty.md` (ADIS-490 Track A). Changelog: `CHANGELOG.md`. Tracker: CCE-138.

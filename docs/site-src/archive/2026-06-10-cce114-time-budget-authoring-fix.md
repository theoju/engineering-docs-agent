---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# CCE-114: the time budget now bounds the authoring fan-out, not just PR admission

Six consecutive scheduled nightlies (2026-06-05 through 2026-06-10) hit the workflow's 60-minute hard kill mid page-author fan-out, discarding an hour of Opus dispatches each time with no PR opened and no baseline advance — CCE-114 closes that gap by checking the soft deadline inside the authoring, fact-checker, and gap-detector loops, not only at PR admission.

## The gap

`resolve_time_budget` (`scripts/orchestrator_runner.py:339`) resolves a soft per-run deadline — default `DEFAULT_TIME_BUDGET_SECONDS = 2700` (45 minutes), kept safely under the workflow's `timeout-minutes: 60` hard kill. `run()` computes it once, up front: `deadline = clock() + budget if budget > 0 else None` (`scripts/orchestrator_runner.py:1226-1227`).

CCE-109 wired that deadline into exactly one place: the PR-admission loop (`scripts/orchestrator_runner.py:1359-1375`), which checks `clock() > deadline` before summarizing each PR and truncates the admitted set when it trips. Admission is cheap and finishes within minutes of a run starting. The expensive phase is the page-author fan-out that follows — one Claude dispatch per `(lens, page_hint)` batch, up to 43 of roughly 50 total dispatches in a backlog window. Nothing checked the deadline there, so a big window sailed straight through the budget into the job's hard kill. That happened on six straight scheduled nightlies, each one losing the entire hour of Opus dispatches with no PR opened and no `state.json` advance — exactly the doom loop CCE-109 was meant to break. Forensics for the last of the six are archived under `docs-agent-subagent-forensics-27263616736-1`.

## The fix

CCE-114 pushes the same deadline check into every loop downstream of admission that was still running unbounded:

- **Authoring** (`scripts/orchestrator_runner.py:1433-1446`): before dispatching `page-author` for batch `i` of `per_target.items()`, the loop checks `deadline is not None and i > 0 and clock() > deadline`. The `i > 0` guard mirrors admission's at-least-one-progress rule — even a tight budget still authors one page batch before deferring the rest. A trip adds a `time_budget_exceeded: authored i/N page batches (budget Bs); deferring the rest` partial reason and breaks the loop; the remaining batches are left for the next run.
- **Fact-checker** (`scripts/orchestrator_runner.py:1603-1617`): before dispatching `fact-checker` for page `i` of the surviving authored pages, the loop checks `deadline is not None and clock() > deadline` — no at-least-one guarantee this time, because this is an advisory warn-only layer and every post-deadline second risks the hard kill. A trip adds `time_budget_exceeded: fact-checked i/N pages (budget Bs); skipping the rest` and breaks outright.
- **Gap detector** (`scripts/orchestrator_runner.py:1719-1731`): same posture, same shape of check, `time_budget_exceeded: gap-checked i/N PRs (budget Bs); skipping the rest`.

The fact-checker skip is the one CCE-114 reason that is deliberately **not** `info_only`. Every other fact-checker-loop reason (`fact_checker_unavailable`, prose-contamination rescues) stays advisory, but a time-budget skip flips the run to `partial` on purpose: pages that were never fact-checked must not pass the CCE-101 auto-merge gate, which keys off `partial == false`. Authoring and gap-detector cuts already flipped `partial` through the existing `add_partial` default.

When any of these loops trips, the run does not keep grinding — it falls through to lint, the deterministic site generators, and PR-open tail work with whatever pages were authored, so a truncated run still produces a reviewable partial PR instead of nothing.

## Verified in tests

`tests/orchestrator/test_time_budget_authoring.py` pins all three guards with a fake monotonic clock over a fixture that gives the summarizer three doc targets, so the authoring loop runs three batches instead of one:

- `test_authoring_loop_truncates_after_budget` — the deadline trips between batch 0 and batch 1; `alpha.md` is written, `beta.md` and `gamma.md` are not, and the partial reason names `authored 1/3 page batches`.
- `test_fact_checker_loop_skips_after_budget` — authoring finishes inside budget (all three pages exist, including `gamma.md`), but the deadline trips before the first fact-checker dispatch; the reason names `fact-checked 0/3 pages`, and authoring itself is confirmed not cut.
- `test_gap_detector_loop_skips_after_budget` — fact-checking clears (the dry-run pages cite nothing, so it never dispatches), but the deadline trips before gap detection; the reason names `gap-checked 0/3 PRs`, and no `fact-checked` reason is also present.
- `test_unlimited_budget_authors_all_targets` — `time_budget_seconds=0` (unlimited) authors all three targets, `partial` stays `false`, and no `time_budget_exceeded` reason appears at all — the control case.

## Why this matters for auto-merge

None of these cuts are silent. Every `time_budget_exceeded` reason flips `current_run.partial = True`, and the CCE-101 merge gate's first eligibility check is `partial == false` — a truncated run stays open for operator review instead of auto-merging half-authored or under-checked content. See `docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md` for the full auto-merge eligibility chain.

## References

- PR #136, tracker CCE-114.
- `CHANGELOG.md` — Unreleased → Fixed.
- Originating incident: scheduled run `27263616736`; forensics artifact `docs-agent-subagent-forensics-27263616736-1`.
- Related: CCE-109 (the original soft-deadline admission gate this extends), CCE-101 (the auto-merge gate that `partial` protects).

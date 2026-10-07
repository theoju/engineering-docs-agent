---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/283
synthesized_into: []
doc_kind: decision
---

# CCE-169: cap the review window before admission

**Decision:** the orchestrator admits at most `run.window_pr_cap` merged PRs per run, oldest first. The default is 10. PRs beyond the cap wait for a later run. Setting the key to `0` restores the unbounded window.

## Context

The review window had no upper bound. `orchestrator_runner.run` in `scripts/orchestrator_runner.py` took every PR that `source-collector` returned since `last_successful_run.head_sha`. The only truncation was the time-budget cut inside the admission loop, which fires after the run has already started failing to keep up.

That made a stall self-reinforcing:

1. The baseline freezes.
2. The window widens by a day.
3. The next run finishes a smaller fraction of it and still earns no cursor prefix.
4. The PR is auto-closed and the baseline stays frozen.

Each stalled night raised the cost of recovery. On the ADIS host the window reached 113 merged PRs and 152 page batches over sixteen consecutive green runs. An operator had to advance the baseline by hand and write the skipped PRs off as a documented gap.

A larger time budget does not fix this. ADIS was already at the largest budget its one-hour App token allows, and it still authored 3 of 152 batches.

## Decision

Bound the window by **PR count**, applied after the PRs are ordered oldest-first and before the summarize loop.

- **Why PR count.** Days since baseline is a poor cost proxy: on this repo a quiet day is 2 PRs and a busy one is 6. Page batches is the truest unit, but it is unknown until `pr-summarizer` has run, so it can only cut mid-run, which is where the time budget already fails. A PR's page group is the unit that must finish atomically, so PR count tracks what has to complete.
- **Why before the summarize loop.** Capped PRs then cost no `pr-summarizer` dispatch. The run has one shared deadline, so the dispatches it skips return wall clock to the authoring loop.
- **Why 10, on by default.** Every CCE-169 incident hit a host that had configured nothing, and an opt-in guard against a silent loss is only discovered by having the loss. Over a pinned 90-day window of this repo's history, no day exceeded 10 admitted PRs, so a healthy host never hits the cap. Erring low is deliberate: a cap that is too tight emits a visible reason nightly and is easy to raise, while one that is too loose produces the silent stall.

The config key lives under `run` in `templates/config.schema.json`. That block rejects unknown keys, so a host that writes `window_pr_cap` fails config load unless the schema declares it.

## How capped PRs are treated

Capped PRs are held in their own category, not in the list of PRs deferred by the time budget. Deferred PRs are ones the run tried and ran out of time on. Capped PRs are ones the run deliberately did not try. Per CCE-144, classification follows the call site, not the resemblance.

- **The cursor stops at the cap boundary.** Capped PRs count as held back. Without that, the run would document 10 PRs and advance the baseline to window HEAD, silently losing the rest. That is the CCE-151 incident reproduced inside the fix for stalls.
- **Capped PRs accrue no deferral counts.** Putting them in the window would delete any deferral history they had earned, and disarm the deferral skip for them.
- **The deferral skip never sees them.** A capped PR already at the skip threshold must not be abandoned for work the run never attempted.

## Why it converges

Held PRs make the cursor walk stop at the cap boundary. The run is then cursor-backed, so CCE-140's carve-out lets the auto-merge proceed. `state.json` reaches the default branch, the baseline advances, and the next run takes the next batch. A cap of 10 drains this repo's 19-PR backlog in about two nights. CCE-178's stall escape, by contrast, forgives one PR per stalled night and cannot keep up with a window that keeps filling.

## Reporting

A capped run records one reason, `held_back_window_capped`, in the form `9 of 19 PRs held for a later run (cap 10)`. It is classified as degraded, not blind: the run held back work rather than consuming input it could not process. It is not in the merge-veto prefixes, because a capped run is the healthy case and must merge.

The reason is deliberately not part of the `time_budget_*` family. The cap fires before any clock is consulted, so a `time_budget_*` label would misreport the cause. The existing `time_budget_*` strings are unchanged.

## Accepted risks

- A host that sustainably merges more than the cap per day never drains its backlog. It emits the reason every night, so the failure is loud.
- The default changes behavior for existing hosts: the cap fires on the first run after it lands. That drain is the intended behavior and loses no content.
- A single PR whose page group cannot finish inside the budget is **not** fixed here. The cap cannot manufacture a cursor in that case. That half of CCE-169 is tracked as CCE-155 (resumable page groups).

## References

- Spec: `docs/superpowers/specs/2026-09-23-cce169-window-cap-design.md`
- Plan: `docs/superpowers/plans/2026-09-23-cce169-window-cap.md`
- Runtime behavior: `docs/site-src/architecture/orchestrator.md`
- Related: CCE-140 (cursor-backed advance), CCE-144 (blind vs degraded), CCE-151 (cursor walk on every path), CCE-155, CCE-175 and CCE-178 (stall escape)

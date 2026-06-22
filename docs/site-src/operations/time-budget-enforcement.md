---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
---

# Time-budget enforcement

The nightly GitHub Actions job has a 60-minute hard kill timeout. Without a matching soft deadline inside the orchestrator, a large backlog window could spawn dozens of Opus dispatches after the budget expired and lose an hour of work with nothing committed. Six consecutive runs hit this ceiling (most recently run `27263616736` on 2026-06-10 UTC), each one discarding progress and growing the unprocessed window by one day.

CCE-109 introduced a soft deadline, but wired it only to PR admission — once the run entered its fan-out loops, no check stopped new dispatches from starting. CCE-114 closed that gap by pushing the deadline check into every loop that spawns a subagent.

## The three cut points

**Page-author fan-out loop.** Before each authoring batch, the orchestrator checks the monotonic clock against the soft deadline. If the budget is exhausted, the remaining pages are skipped and no further Opus dispatches are made. An at-least-one-batch guarantee applies: even with a very tight budget, the first batch always runs so the PR is never empty.

**Fact-checker loop.** Once the deadline has passed, the per-page fact-checker skips outright. Pages authored in the current run that were not fact-checked remain in the PR with their content, but the run is marked partial.

**Gap-detector loop.** Same behavior as the fact-checker. If the deadline is expired when the gap-detector loop starts, it skips entirely and the run is marked partial.

## The `partial` flag

Any loop that is cut by the deadline sets `partial=true` on the run result. This flag is load-bearing: the CCE-101 auto-merge gate will not squash-merge a partial PR. The PR stays open, visible, and operator-actionable rather than being silently merged with incomplete coverage.

The `state.json.last_successful_run` cursor does not advance until the PR merges. If the PR stays open, the next nightly run extends the window to cover the same period again.

## Operator decision flow

When you see a partial PR, you have two options.

**Merge and accept the coverage gap.** The authored pages are in the PR. The fact-checker and/or gap-detector did not run, so some accuracy and gap signals are missing. If the authored content looks correct and the coverage gap is acceptable, merge manually. The cursor advances and the next nightly run starts from the new head SHA.

**Leave open and let the next run retry.** If the run was cut because the window was unusually large (e.g., after several missed days), the next nightly run will restart from the same cursor, author any remaining pages, and attempt fact-checking and gap detection again. The PR stays open; a new commit is appended to the same branch.

## Diagnosing a partial run

Check the PR body for the `partial: true` marker. The body also lists which stages completed and which were skipped. For deeper diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` and re-run; each subagent's raw stdout lands in a timestamped file there.

The soft deadline itself is configured via `time_budget_seconds` in the host config. The default matches the GitHub Actions job timeout with a buffer; tighten it if your host's Actions runner has a shorter wall-clock limit.

---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
---

# Time Budget

The orchestrator runner operates under a soft time budget enforced across every expensive loop phase. The budget exists to prevent the nightly GitHub Actions job from hitting its hard 60-minute timeout and discarding an hour of Opus work with no state advancement.

## Deadline source

The deadline is established once at run start (CCE-109) and stored in the run's shared state. Every phase that dispatches subagents reads from this single wall-clock expiry — there is no per-phase budget, only one deadline shared across the whole run.

## Per-phase enforcement

### Page-author fan-out

Before each batch of page-author dispatches, the runner checks the deadline. If the budget is already expired, the authoring loop stops — but only after at least one batch has been dispatched. The at-least-one-progress guarantee means a tight budget still crawls forward rather than producing a completely empty run.

The page-author fan-out can reach up to 43 Opus dispatches in a backlog window. Before CCE-114, these dispatches ran unbounded past the deadline. Six consecutive nightlies (June 5–10, 2026) were killed at the 60-minute GitHub Actions job timeout because roughly 20 dispatches started after the soft deadline; each run discarded all work and advanced no state. Run 27263616736 (2026-06-10 08:30 UTC) provided the forensic trace confirming the gap.

### Fact-checker loop

Once the budget is expired, the fact-checker loop is skipped entirely. The runner sets `partial: true` on the run, which blocks auto-merge per the CCE-101 gate.

### Gap-detector loop

Same posture as the fact-checker: skipped outright when the budget is expired. The run is already marked partial before the gap-detector would fire, so the skip is a no-op from a partial-semantics perspective — but it still saves wall-clock time and avoids starting work that cannot finish.

## Partial semantics

A run is marked `partial: true` whenever any phase was truncated by the time budget. Partial runs follow these invariants:

- **Do not auto-merge.** The CCE-101 auto-merge gate rejects partial runs unconditionally. The PR is left open with a visible `auto_merge_skipped` reason in the body.
- **Still open a PR.** Per spec §8, a partial run opens (or appends to) the `docs-agent/YYYY-MM-DD` PR with `partial: true` in the body. The operational gap is visible, not silent.
- **Do not advance `last_successful_run`.** The state cursor only advances when the operator merges the PR. Until then, `state.json.last_successful_run` remains at the previous successful run's `head_sha`.

This posture deliberately mirrors the PR-admission partial pattern from CCE-101 — partial is partial regardless of the cause.

## Operator options on a partial PR

When you see a partial docs-agent PR, you have three options:

**Merge manually.** Review the authored pages, confirm no egregious errors, and merge. The state cursor advances to the new `head_sha` and the next nightly runs from there.

**Re-trigger the nightly.** If the partial run was caused by a transient constraint (an unusually large backlog, an ephemeral slow runner), fire a manual nightly:

```bash
gh workflow run docs-agent-nightly.yml -f reason="retry after partial"
gh run watch
```

The runner picks up from the same `since` SHA and attempts the remaining work. If the new run completes without truncation, it will auto-merge normally.

**Close without merging.** If the partial content is stale or superseded, close the PR without merging. `state.json.last_successful_run` does not advance, and the D2 auto-close sweep handles superseded open PRs automatically.

## Test coverage

Four TDD-driven tests in `tests/orchestrator/test_time_budget_authoring.py` exercise this contract:

- Authoring truncation — verifies files on disk after a mid-fan-out deadline expiry and confirms `partial: true`
- Fact-checker skip — confirms the phase is bypassed when budget is expired
- Gap-detector skip — same posture as the fact-checker test
- Unlimited-budget passthrough — confirms all three phases run when no deadline is configured

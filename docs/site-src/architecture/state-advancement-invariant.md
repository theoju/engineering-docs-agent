---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# §8 State-Advancement Invariant

The §8 state-advancement invariant governs how the orchestrator responds to failures during a nightly run. It defines exactly two outcomes — partial continuation and hard stop — and specifies which class of failure triggers each.

## The two contract branches

**Subagent crash or timeout → partial, continue.**
When a subagent exits non-zero or times out, the orchestrator catches the error and sets `current_run.partial = true` before moving on. The run continues to the PR create/update step. The resulting PR body includes `partial: true` so the operational gap is visible, not silent. No data is silently discarded.

**PR create/update failure → hard stop.**
If the PR creation or update itself fails, the orchestrator returns `1` immediately. There is no partial PR body written, no state advancement. The failure is surfaced at the workflow level and must be resolved before the next nightly run attempts to advance the commit window.

## Why the distinction matters

A subagent failure is recoverable in context: other subagents' output is still valid, the docs-PR still has value, and an operator can re-run the failing agent manually. A PR failure means no artifact was delivered at all — advancing state would silently skip the affected changes on the next run.

The invariant ensures that `last_successful_run.head_sha` in `.engineering-docs-agent/state.json` only advances when a PR actually lands. A partial run opens a PR marked `partial: true`; that PR, once merged, still advances the SHA. The gap is flagged but not lost.

## Post-CCE-40/CCE-41 audit (2026-05-29)

After landing CCE-40 (durable state persistence) and CCE-41 (subagent forensics in CI), the team audited whether the invariant still held under the new infrastructure. The verdict: no regression. The production code required no changes — both branches of the contract were already correctly implemented. The audit confirmed:

- `current_run.json` writes happen before the orchestrator proceeds past a failing subagent, so crash recovery does not lose the `partial` flag.
- The hard-stop path on PR failure does not interact with the durable-state write path — state is only committed to `.engineering-docs-agent/state.json` as part of a successful PR merge, not inline during the run.

See `docs/superpowers/plans/` for the full audit methodology and `archive/2026-05-29-state-advancement-audit.md` for the decision record.

## Regression test coverage

PR #81 (CCE-62) added three regression tests that pin both branches:

1. **Subagent failure → `partial=true`, run continues** — asserts that a non-zero subagent exit sets the flag and does not halt orchestration.
2. **PR create failure → `return 1`** — asserts the orchestrator exits immediately on a PR API failure without advancing state.
3. **Happy path** — asserts that a clean run produces no `partial` flag and returns `0`.

These tests live alongside the orchestrator integration tests. If you refactor the error-handling path in `scripts/orchestrator_runner.py`, run the full suite (`python3 -m pytest`) and confirm all three pass before merging.

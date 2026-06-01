---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# §8 State-Advancement Invariant

The orchestrator tracks the last successfully processed commit in `.engineering-docs-agent/state.json` under `last_successful_run.head_sha`. The §8 invariant governs exactly when that value advances and what "advance" means across the two failure modes the nightly run can encounter.

## The two branches of the contract

**Branch 1 — subagent errors during a partial run.** When one or more subagents fail mid-run, the orchestrator still advances `last_successful_run.head_sha` on disk before attempting to open the PR. The PR body carries `partial: true` so the operational gap is visible rather than silent. The on-disk advance is intentional: it prevents the same erroring commits from piling up in every subsequent nightly window while the underlying failure is investigated.

**Branch 2 — PR-create or PR-update failure.** When the GitHub API call to open or append to the `docs-agent/YYYY-MM-DD` PR fails, the on-disk advance already written is ephemeral. The CI runner's fresh checkout on the next nightly fire restores `state.json` from `main`, which has not been updated. The effective head SHA on `main` remains un-advanced until a docs-agent PR successfully merges.

## Why the ephemeral advance is safe

The CI fresh-checkout cycle is the enforcing mechanism. Each nightly run starts from a clean clone, so any on-disk mutations in the working tree — including an updated `state.json` — are discarded when the run ends without merging. Only a merged docs-agent PR carries the updated `state.json` into `main`, making that advance durable.

This design is documented in the CCE-40 §7 explicit design choice: gate the state advance before PR-open, not after. The alternative — advancing only on successful PR merge — would require a separate promote step and creates a race between the publish-verification stage and the next nightly fire.

## Code locations

- `orchestrator_runner.py` — the advance write happens before the `open_or_update_pr` call; grep for `last_successful_run` to find the exact line.
- `state_io.py` — `write_state` is the helper that persists the advance to disk; it is called unconditionally on partial runs.

## Regression tests

PR #81 added three tests to pin this contract. All three live in the orchestrator test suite:

1. **`test_partial_run_advances_state_on_disk`** — confirms that a run with one subagent error still writes the advanced SHA to disk.
2. **`test_main_state_not_advanced_without_merged_pr`** — confirms that without a merged PR, the effective SHA on `main` is unchanged after a partial run.
3. **`test_pr_open_failure_returns_1_and_acknowledges_ephemeral_advance`** — confirms that a PR-open failure exits non-zero and leaves the on-disk advance ephemeral. This test is intentionally designed so that gating the state advance on PR success breaks the test, forcing an explicit spec update rather than a silent regression.

No source code in `scripts/` or `agents/` changed in PR #81. The audit confirmed the invariant already held; the tests exist to prevent a future refactor from breaking it silently.

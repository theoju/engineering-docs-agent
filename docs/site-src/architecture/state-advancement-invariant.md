---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# State-Advancement Invariant

The orchestrator guarantees that every run — including partial failures — advances the on-disk state forward. This is the §8 state-advancement invariant.

## The two-branch contract

The invariant has exactly two branches depending on where the failure occurs.

**Branch 1 — subagent crash or timeout.** The orchestrator catches the error, marks `partial=true` in the run state, and still commits the updated state to the docs-agent branch. The PR body surfaces the partial flag so the gap is visible. State advances; `last_successful_run.head_sha` moves forward.

**Branch 2 — PR create/update failure.** The orchestrator exits with `return 1` and does _not_ promote `last_successful_run.head_sha`. The on-disk state file is written before the PR step, so the local advance is preserved for diagnostics. The CI checkout cycle is the enforcement mechanism: until a docs-agent PR merges to `main`, `origin/main`'s `last_successful_run.head_sha` does not move. No silent skipping of commits.

## Why the distinction matters

A subagent failure is recoverable mid-run. The orchestrator has already done useful work and the partial output is worth landing. Suppressing the commit would silently re-process the same input window on the next nightly run.

A PR-layer failure is different. The docs-agent branch may be in an inconsistent state. Hard-exiting without promoting `head_sha` forces a fresh retry against the same window — you see the failure in CI, and nothing is swept under the rug.

## Audit history

CCE-40 introduced durable state persistence (state committed to git, not kept only in memory). CCE-41 introduced subagent forensics (per-subagent stdout capture in `DOCS_AGENT_DEBUG_DIR`). Both changes touched the code paths that write and advance state.

CCE-62 (PR #81) audited the invariant after those two merges to confirm neither change had silently broken it. The audit verdict was clean — no production code required modification. Three regression tests were added to pin both contract branches and prevent future regressions from going undetected.

## Regression test coverage

The three tests added in CCE-62 cover:

1. Subagent crash → `partial=true` is set, state file is committed to the docs-agent branch.
2. Subagent timeout → same outcome as crash; orchestrator does not block on the hung agent.
3. PR create/update failure → `return 1`, `last_successful_run.head_sha` is not promoted in the committed state.

All three tests use the fixture-driven dry-run path; the production GitHub API call is monkeypatched.

## Updating this contract

If you change the orchestrator so that PR success gates state advancement, you must update the spec (`docs/superpowers/specs/`), update these tests, and update this page in the same PR. The three artifacts must stay in sync — the spec describes the intent, the tests pin the behavior, and this page communicates both to the team.

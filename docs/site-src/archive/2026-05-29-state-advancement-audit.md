---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# §8 State-Advancement Audit (2026-05-29)

**Outcome: invariant holds. No code change required.**

## Background

CCE-40 introduced durable state persistence. CCE-41 added subagent forensics. After both landed, PR #81 ran a formal audit of the §8 state-advancement contract to confirm neither change silently broke it.

The §8 invariant is: the orchestrator advances on-disk state regardless of whether a downstream action (subagent execution or PR create/update) succeeds or fails.

## What the audit confirmed

**Subagent crash or timeout.** When a subagent exits non-zero or times out, the orchestrator marks the run `partial: true` and records the failure in `partial_reasons`. State still advances on disk. The next CI checkout cycle sees a valid state file and can proceed without operator intervention.

**PR create/update failure.** When the GitHub API call to open or update the docs PR fails, the orchestrator returns exit code 1. The on-disk state advance already happened before the PR call. The CI checkout cycle inherits the advanced state and retries only the PR step — it does not re-run subagents.

Neither failure path gates state advancement on success of the downstream action. That is the invariant.

## Regression tests

Three tests were added to pin both branches of the contract against future regressions. If any future refactor gates state advancement on PR success, these tests fail and require an explicit spec and test update before merging.

The tests live alongside the orchestrator's existing suite. They use the fixture-driven dry-run path; no live API or LLM calls are made.

## Why this matters

Without pinned tests, a well-intentioned change — say, "only advance state after the PR is confirmed open" — would silently invert the contract. That would cause repeated subagent runs on a PR-API outage, duplicating work and potentially emitting conflicting docs updates.

The audit is also evidence for future contributors: the state-advance-before-PR-call ordering is deliberate, not an accident of implementation sequence.

## Related

- CCE-40: durable state persistence
- CCE-41: subagent forensics
- PR #81: [audit and regression tests](https://github.com/theoju/engineering-docs-agent/pull/81)

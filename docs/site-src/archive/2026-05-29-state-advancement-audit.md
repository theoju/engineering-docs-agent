---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# State-Advancement Invariant Audit — 2026-05-29

**Jira:** CCE-62  
**Audited by:** PR #81 (no production code changed)  
**Verdict:** Invariant holds. No regression introduced by CCE-40 or CCE-41.

## Context

CCE-40 landed durable state persistence and CCE-41 added subagent forensics in CI. Both changes touched the orchestrator's error-handling path. After both PRs merged, CCE-62 audited whether the §8 state-advancement contract still held correctly under the new infrastructure.

The §8 contract has two branches:

1. **Subagent crash or timeout** — the orchestrator catches the error and marks `current_run.partial = true` before continuing to the next stage. The run is not aborted.
2. **PR create/update failure** — the orchestrator performs a hard stop (`return 1`). The run does not continue.

## Findings

The audit confirmed both branches behave correctly without any code change. CCE-40's durable-state writes happen before the error-catch boundary, so a subagent failure does not roll back the persisted state. CCE-41's forensic capture happens inside the same catch block, so it never interferes with the `partial = true` flag.

No silent regression was introduced.

## Outcome

Three regression tests were added to pin both contract branches explicitly:

- One test exercises the subagent-crash path and asserts `current_run.partial == True` after the catch.
- One test exercises the timeout path and makes the same assertion.
- One test exercises the PR-create-failure path and asserts `return 1` (hard stop, no `partial` flag set).

These tests live alongside the orchestrator test suite. Any future refactor that silently breaks either branch will fail here before reaching CI.

A plans document and a design-spec document capturing the audit methodology were also committed with this PR and serve as the authoritative reference for the §8 contract rationale.

## Decision

No production code change required. The invariant was already correctly implemented. The regression tests are the durable artifact: they prevent future regressions and serve as executable documentation of the two contract branches.

See the architecture page at `docs/site-src/core/architecture/state-advancement-invariant.md` for the full contract specification.

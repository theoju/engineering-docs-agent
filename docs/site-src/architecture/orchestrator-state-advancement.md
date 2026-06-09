---
description: "The orchestrator runner advances state.json only under specific conditions."
source_files:
  - scripts/orchestrator_runner.py
last_reviewed: "2026-06-09"
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# Orchestrator State Advancement

The orchestrator runner advances `state.json` only under specific conditions. This page defines those conditions as formal invariants, explains the sentinel file that exposes them to callers, and lists the tests that close the regression surface.

## Why advancement correctness matters

`state.json.last_successful_run.head_sha` is the cursor for the next nightly run. If the cursor advances after a partial run, the next run silently skips PRs that were never fully processed. If it regresses, the next run re-processes PRs that already landed in docs — producing duplicate entries. Neither failure mode is loud; both corrupt the docs site incrementally.

## The three invariants

These invariants are the contract every future change to `orchestrator_runner.py` must preserve.

**Invariant 1 — no advance on partial.** The runner must not update `state.json` when a run completes with `partial: true`. A partial run means at least one subagent stage failed or produced an empty output. The cursor must stay pinned at the last clean SHA so the next run retries the same window.

**Invariant 2 — advance on clean.** The runner must update `state.json` after every fully clean run (all stages pass, `partial: false`). Failing to advance on a clean run has the same effect as a regression: the next run reprocesses already-documented PRs.

**Invariant 3 — no SHA regression.** The new cursor must be a descendant of (or equal to) the current cursor. A cursor that goes backwards reopens an already-closed window and re-ingests history. This invariant is checked by comparing the new SHA against the current one using `git merge-base --is-ancestor`.

## Sentinel file

After every `run()` call — whether it ends cleanly or partially — the runner writes:

```text
.engineering-docs-agent/last_run_invariant.json
```

Schema:

```json
{
  "advanced": true | false,
  "reason": "<human-readable explanation>"
}
```

`advanced` is `true` only when the cursor was updated. `reason` is a short string describing why advancement was taken or skipped (e.g., `"clean run"`, `"partial: page-author failed"`, `"sha regression detected"`).

The sentinel file is gitignored and ephemeral — it is overwritten on every run. Its purpose is to give the calling workflow a machine-readable signal without having to parse the full run log. See [Sentinel File Verification](../operations/sentinel-file-verification.md) for how to consume it in a workflow.

## Invariant tests

Three parametrized tests in the orchestrator runner test suite close the regression surface. Each test drives `run()` through a fixture-backed dry-run path:

| Test                                 | What it asserts                                                                 |
| ------------------------------------ | ------------------------------------------------------------------------------- |
| `test_state_not_advanced_on_partial` | `state.json` cursor is unchanged; sentinel `advanced == false`                  |
| `test_state_advanced_on_clean`       | `state.json` cursor moves to the new head SHA; sentinel `advanced == true`      |
| `test_state_no_sha_regression`       | Attempting to advance to an ancestor SHA raises and leaves the cursor unchanged |

All three use the fixture-driven dry-run path; the production Claude CLI dispatch is monkeypatched. Add a test here before changing any advancement logic — failing test first, implementation second.

## Implementation reference

The advancement logic lives in `scripts/orchestrator_runner.py`. The sentinel write happens unconditionally at the end of `run()`, after the conditional `state.json` update. If you move or rename either call site, update both together — a sentinel that doesn't reflect the actual advancement decision is worse than no sentinel.

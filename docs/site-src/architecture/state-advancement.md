---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# State-Advancement Invariant (§8)

The orchestrator's §8 state-advancement contract defines exactly when `last_successful_run.head_sha` advances and when the runner hard-fails. It has two branches.

## Branch 1 — Subagent error or timeout

When a subagent crashes, times out, or returns an error payload, the orchestrator **continues**. The docs-agent PR opens with `(partial)` in its body. The `last_successful_run.head_sha` in `state.json` still advances to `HEAD` on the docs-agent branch.

This is intentional. Operators see the partial flag and decide whether to merge. A silent skip would leave the error invisible in the commit history.

The relevant design table entry is CCE-40 §7 row 4.

## Branch 2 — PR open/update failure

When the PR create or update step itself fails, the runner hard-fails and returns exit code `1`. No PR is opened; no partial PR is left open.

The on-disk `state.json` write still happens as a working-tree change, but `actions/checkout@v5` provisions a fresh tree on the next nightly fire, so the un-pushed advance never reaches `main`. The advance is intentionally ephemeral in this path.

The relevant design table entry is CCE-40 §7 row 3.

## Regression test coverage

Three tests in `tests/orchestrator/test_state_advancement_invariant.py` pin both branches:

| Test | Scenario | Expected outcome |
|---|---|---|
| `test_partial_run_via_source_collector_error_advances_state` | Source-collector returns `error` + `partial: true` | Exit 0; `head_sha` advances; `current_run.partial` is `True` |
| `test_partial_run_via_lint_block_advances_state` | Content-validator returns a block-severity failure | Exit 0; `head_sha` advances; blocked file unlinked; `partial: true` |
| `test_pr_open_failure_returns_1_and_records_partial_reason` | `open_or_append_pr` returns failure | Exit 1; `head_sha` advances on disk (ephemeral); `partial_reasons` populated |

These tests were added in PR #81 as part of a targeted audit following the CCE-40 (durable state persistence) and CCE-41 (subagent forensics) changes. The audit confirmed the invariant holds end-to-end with no code corrections required.

## What `current_run` does and does not persist

`current_run` lives in `.engineering-docs-agent/current_run.json` — a gitignored ephemeral file written every state-update. It never appears inside the committed `state.json`. If you see `current_run` in `state.json`, that is a bug: the regression test at `tests/orchestrator/test_state_advancement_invariant.py:132` will catch it.

## Relationship to CCE-40 and CCE-41

CCE-40 introduced the durable-state split: persistent `state.json` vs. ephemeral `current_run.json`. CCE-41 added subagent forensics that capture stdout/stderr from failing subagents for diagnostics. The §8 invariant was audited post-hoc to confirm both features coexist correctly with partial-run and PR-failure paths.

If you change either the state-persistence logic (`scripts/state_io.py`) or the PR-open path (`scripts/orchestrator_runner.py`), run the three regression tests above before merging. They are the canonical guard for this contract.

---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# State-Advancement Invariant (§8)

The orchestrator guarantees that `state.json` is written to disk whenever a run produces a meaningful result — whether the run completes cleanly or stops early. This contract is called the **§8 state-advancement invariant**. CCE-62 audited the post-CCE-40 (durable state persistence) and post-CCE-41 (subagent forensics) codebase against this contract and confirmed compliance.

## The two branches

**Branch 1 — partial run.** When a subagent fails with `source_collector_error` or `lint_block`, the run continues in partial mode. The orchestrator still calls `advance_state()` before exiting, writing `state.json` to disk with `partial: true` and a `partial_reasons` list. The nightly PR opens with `partial: true` in its body so the operational gap is visible, not silent.

**Branch 2 — PR-open failure.** When the nightly PR cannot be opened (e.g., a GitHub API error after all subagents complete), `run()` returns exit code 1. The on-disk `state.json` advance is **preserved** — it already happened as part of the working-tree write in the same run. The advance is treated as ephemeral (CCE-40 §7 row 3): it persists in the working tree but is only promoted to `main` if the docs-agent PR itself merges. No separate promote workflow is needed.

## The merge-as-promotion model (CCE-40)

`state.json` is a committed file in `.engineering-docs-agent/`. When the docs-agent PR merges, the updated `state.json` lands on `main` as part of the normal merge — the merge _is_ the promotion. `last_successful_run.head_sha` advances automatically; the next nightly run reads the new baseline from `main`.

This design means a partial run's `state.json` is visible in the feature branch but does not contaminate `main` unless the PR is accepted. A PR-open failure leaves the local `state.json` written but never pushed, so `main` is unaffected.

## Regression coverage

PR #81 added three deterministic fixture-driven tests that pin both branches:

1. A `source_collector_error` partial run writes `state.json` with `partial: true` set.
2. A `lint_block` partial run does the same.
3. A PR-open failure causes `run()` to return 1 while the working-tree `state.json` advance is already present on disk.

All three tests use the standard dry-run path (production Claude CLI dispatch is monkeypatched). Any future refactor that breaks either branch of the invariant fails loudly instead of silently.

## Where to look

- `scripts/orchestrator_runner.py` — `run()` function; look for the `advance_state()` call sites.
- `scripts/state_io.py` — `advance_state()` and `write_state()` implementations.
- `scripts/contracts.py` — `RunState` dataclass; `partial` and `partial_reasons` fields.
- `.engineering-docs-agent/state.json` — committed state on `main`; `last_successful_run.head_sha` is the nightly baseline.
- `tests/` — the three CCE-62 regression tests for this contract.

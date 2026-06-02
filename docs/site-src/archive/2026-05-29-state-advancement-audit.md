---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# State-Advancement Audit — 2026-05-29

**Jira:** CCE-62 | **Verdict:** invariant holds, no code change required

## Background

Two earlier tickets changed how the orchestrator manages state:

- **CCE-40** introduced durable `state.json` persistence — each partial-run cycle now writes its progress before exiting.
- **CCE-41** added subagent forensics collection to CI — failure artifacts are captured and surfaced in GitHub Actions.

Neither ticket included a formal verification that the §8 state-advancement guarantee still held after both changes landed. CCE-62 closed that gap.

## The §8 invariant

The state-advancement contract says: every partial-run cycle must either advance the persisted state or surface an error. The orchestrator must never silently stall — leaving `state.json` unchanged while reporting no failure.

Two branches of the contract were under scrutiny:

1. **Advance path** — a cycle that completes at least one stage writes an updated `head_sha` (or equivalent marker) before exiting.
2. **Error path** — a cycle that fails before advancing records a non-empty `partial_reasons` entry and sets `partial: true`.

## Audit result

The audit confirmed the invariant holds for both branches. CCE-40's persistence layer always writes state after a stage completes; CCE-41's forensics hook fires on exception, ensuring the error path records a reason before propagating.

No code change was required. The audit produced two artefacts:

- A **plans summary** (decision record) documenting the evidence.
- A **spec/design document** covering the contract in detail — published separately at `architecture/2026-05-29-state-advancement-audit-design.md`.

## Regression tests

Three new tests in `tests/orchestrator/test_state_advancement_invariant.py` pin both branches:

| Test | Branch covered |
|------|---------------|
| `test_advance_path_writes_state` | Advance path — verifies `state.json` is updated after a successful stage |
| `test_error_path_records_partial_reason` | Error path — verifies `partial_reasons` is non-empty on exception |
| `test_no_silent_stall_on_empty_cycle` | Edge case — verifies a no-op cycle does not leave state unchanged without a reason |

These tests use the fixture-driven dry-run path; no real Claude CLI dispatch occurs.

## What you should know

If you modify the orchestrator's stage-dispatch loop or the `state.json` write path, run `tests/orchestrator/test_state_advancement_invariant.py` explicitly before opening a PR. A red result there means you have broken the §8 contract.

If you add a new stage, add a corresponding advance-path test and verify the error path is covered by the existing suite or by a new test.

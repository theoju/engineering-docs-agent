---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# State-Advancement Invariant: Audit Design (CCE-62)

**Date:** 2026-05-29  
**Jira:** CCE-62  
**Related:** CCE-40 (durable state.json), CCE-41 (subagent forensics CI)

## Background

§8 of the orchestrator spec defines the state-advancement contract: every partial-run cycle must either advance `state.json` or surface an explicit error. It must never silently stall. CCE-40 introduced durable `state.json` persistence; CCE-41 wired subagent forensics into CI. Neither change was accompanied by a direct verification of the §8 invariant.

CCE-62 closed that gap. The audit verdict: the invariant holds across both code paths — no code change was required. The work product is three regression tests and two documentation artifacts (this design doc and the companion audit summary in `archive/`).

## The Invariant

The state-advancement contract has two branches:

1. **Happy path.** After a complete cycle the orchestrator writes an updated `state.json` with `last_successful_run.head_sha` advanced to the current run's `HEAD`. The state file is committed in the same docs-agent PR.

2. **Partial path.** When any subagent fails or returns `partial: true`, the orchestrator still writes `state.json` — but sets `partial: true` and populates `partial_reasons`. The PR opens with a `partial: true` body flag so the gap is operationally visible.

The invariant is violated if a run exits without writing `state.json` at all, or exits without setting `partial: true` when a subagent failed. Either case produces a silent stall: the next nightly run sees the same `HEAD` and re-processes the same window.

## What CCE-40 Changed

CCE-40 made `state.json` writes durable by introducing an atomic write pattern in `scripts/state_io.py`. Before CCE-40, a crash mid-write could leave a partial JSON file. After CCE-40, the write goes to a temp file then renames into place. The rename is atomic on POSIX filesystems.

The audit confirmed the invariant was not affected: the orchestrator's §8 decision logic (`scripts/orchestrator_runner.py`) runs before the write, not after. A crash during the write produces a stale but valid `state.json` (the previous committed version), not a corrupt one.

## What CCE-41 Changed

CCE-41 added subagent forensics: when `dispatch_subagent` raises or returns a non-zero exit, the runner captures stdout/stderr into `DOCS_AGENT_DEBUG_DIR` and records the failure in `current_run.json`. The `partial: true` flag is set on the same code path that was already setting it.

The audit confirmed that CCE-41 did not introduce a new code path that could bypass the `partial: true` write. The forensics capture happens inside the existing exception handler; the `state.json` write still runs in the `finally` block that surrounds it.

## Regression Tests

Three tests in `tests/orchestrator/test_state_advancement_invariant.py` pin both branches of the contract:

- **`test_full_cycle_advances_head_sha`** — asserts that a complete run updates `last_successful_run.head_sha` in the written `state.json`.
- **`test_partial_cycle_sets_partial_flag`** — asserts that when any subagent returns `partial: true`, the orchestrator writes `partial: true` and a non-empty `partial_reasons` list.
- **`test_crash_during_write_leaves_valid_state`** — simulates an `OSError` mid-write and asserts the previously committed `state.json` is intact (the atomic rename was not completed, so the old file is untouched).

All three tests use the fixture-driven dry-run path; the Claude CLI dispatch is monkeypatched.

## Design Constraints

**No silent exits.** The orchestrator's top-level `try/except` in `orchestrator_runner.py` must never swallow an exception without writing `state.json`. If you add a new early-exit path (e.g., a config validation failure), ensure it either writes a `partial: true` state or re-raises so the caller surfaces the error.

**Partial is not failure.** A run that sets `partial: true` is a successful write — the next nightly window will include the same commits again. Do not treat `partial: true` as a reason to skip the `state.json` write.

**The forensics buffer is not state.** `current_run.json` and the debug dir written by CCE-41 are ephemeral diagnostics. They are not part of the state-advancement contract. The invariant concerns only `state.json`.

## Verification Checklist

When you modify the orchestrator's run loop or the `state_io.py` write path, run:

```bash
python3 -m pytest tests/orchestrator/test_state_advancement_invariant.py -v
```

All three tests must pass before merging. If you add a new early-exit or error-handling code path, add a fourth test that exercises it.

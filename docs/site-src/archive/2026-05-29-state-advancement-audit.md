---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# Audit Record: §8 State-Advancement Invariant (2026-05-29)

**Verdict: invariant holds. No code corrections required.**

## Background

Two recent changes — CCE-40 (durable state persistence) and CCE-41 (subagent forensics) — touched the orchestrator's state management layer. CCE-40 introduced persistent state writes so partial runs survive restarts. CCE-41 added forensic capture of subagent stdout/stderr for diagnostics. Neither change was intended to alter the §8 state-advancement contract, but both were large enough to warrant post-hoc verification.

The §8 invariant states: every orchestrator run must advance `last_successful_run.head_sha` on success and must leave state unchanged on failure, regardless of which stage fails. Partial runs set `partial: true` and record a `partial_reasons` list — they do not advance `head_sha`.

## Scope

The audit covered three scenarios:

1. **Full-success run.** All stages complete without error. `head_sha` advances to the current run's SHA; `partial` is absent or `false`.
2. **Partial run — subagent failure.** One or more subagent dispatches fail. The run opens a PR with `partial: true` in the body. `head_sha` is not advanced; `partial_reasons` names the failed stage.
3. **Retry after partial.** The orchestrator re-runs over the same SHA window. The partial state from the previous run does not block advancement on a subsequent clean run.

No edge cases required code changes. The durable-state write path (CCE-40) already gates `head_sha` advancement behind the final success check. The forensic capture path (CCE-41) writes to a gitignored `current_run.json` and has no effect on committed state.

## Tests pinned

Three regression tests in `tests/orchestrator/test_state_advancement_invariant.py` lock in this behavior:

- `test_full_success_advances_sha` — verifies `head_sha` is written on a clean run.
- `test_partial_run_does_not_advance_sha` — injects a subagent failure mid-run; asserts `head_sha` is unchanged and `partial_reasons` is populated.
- `test_retry_after_partial_advances_sha` — simulates a partial-state file on disk, then runs a clean pass; asserts `head_sha` advances and `partial` is cleared.

All three tests operate on the fixture-driven dry-run path. The production Claude CLI dispatch is monkeypatched per the standard test convention.

## What was not changed

No runtime code was modified. The audit was a read-and-verify pass against the existing implementation. The plan document and design spec added in PR #81 (`docs/superpowers/plans/` and `docs/superpowers/specs/`) capture the methodology for future reference; they are host-specific artifacts and not part of the core doc tree.

## Related pages

- [State-Advancement Invariant](../architecture/state-advancement.md) — the living contract page derived from this audit.

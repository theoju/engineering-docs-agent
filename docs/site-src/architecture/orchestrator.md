---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/62
synthesized_into: []
---

# Orchestrator Runner

`scripts/orchestrator_runner.py` is the entry point for every nightly run. It coordinates the seven subagents, manages state persistence, and opens or appends to the `docs-agent/YYYY-MM-DD` PR.

## Run lifecycle

The `run()` function owns the full lifecycle from config load through PR creation. A `try/finally` block at the top of `run()` guarantees that a step-summary digest flushes to `$GITHUB_STEP_SUMMARY` regardless of how the run exits — clean success, partial completion, or hard failure.

Hard-fail paths include config validation errors, corrupted state, and crashes inside `open_or_append_pr`. All of them reach the `finally` block.

## Partial reasons and step summaries

The orchestrator tracks operational gaps in `state.current_run.partial_reasons`. Each `add_partial(...)` call (22 callsites) appends a string to that list in memory. `save_persistent_state` intentionally strips `current_run` from `state.json` on disk (CCE-40 design), so `partial_reasons` never survives to the state snapshot the workflow cats at the end.

`_write_step_summary(state, repo_root)` solves this. When the process runs inside GitHub Actions (detected via `$GITHUB_STEP_SUMMARY` being set), it calls `_format_partial_digest(partial_reasons)` and appends the result to the step summary file. You get a structured bulleted digest in the workflow summary box without downloading the CCE-41 forensics artifact.

`_write_step_summary` swallows `OSError` — a failure to write the summary never aborts the run.

## Shared digest formatter

`_format_partial_digest(partial_reasons)` is extracted as a standalone helper used by two consumers:

- `_write_step_summary` — writes to `$GITHUB_STEP_SUMMARY`.
- The PR body composer — replaces the old semicolon-joined `WARNING: …` line with a bulleted list.

Both surfaces now render the same structured output. If `partial_reasons` is empty, both surfaces produce no output for that section.

## Test coverage

Nine tests added in PR #62 cover:

- `_format_partial_digest` contract (empty list, single reason, multiple reasons).
- `OSError` swallowing in `_write_step_summary`.
- Hard-fail flush: summary written even when `run()` exits via exception.
- Clean-path positive pin: no spurious partial section when `partial_reasons` is empty.

## Known deferred issues

`.github/workflows/docs-agent-nightly.yml:123` contains a `cat | sed || echo` dead-code chain that is out of scope for PR #62 and deferred to a follow-up. Post-merge manual validation of the actual `$GITHUB_STEP_SUMMARY` GitHub Actions surface is also pending per the PR test plan.

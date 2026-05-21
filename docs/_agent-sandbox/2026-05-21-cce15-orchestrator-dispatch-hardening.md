---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/11
synthesized_into: []
---

# CCE-15: Orchestrator Dispatch Hardening

**Date:** 2026-05-21
**Ticket:** CCE-15
**PR:** [#11](https://github.com/theoju/engineering-docs-agent/pull/11)

## Background

CCE-14's 5-run baseline surfaced three root-cause failure modes in source-collector dispatch:

1. **Category-A structural bypass** — the Claude response structure itself bypassed validation entirely.
2. **Prose preamble contamination** — user-level Claude settings injected a SessionStart hook that prepended explanatory prose to JSON output.
3. **Phantom-field silent acceptance** — fields not in the schema passed validation without error.

CCE-15 targeted the two tractable categories — contamination and phantom keys — and deferred the structural Category-A issue to CCE-16 after empirical confirmation that `--bare` breaks OAuth.

## What Changed

### 1. Exclude user-level Claude settings from dispatch

`dispatch_subagent` now passes `--setting-sources project,local` when invoking the Claude CLI. This drops the user-level settings layer, which hosts a SessionStart hook that injects prose preamble into subagent output. OAuth keychain access is preserved because `project` and `local` settings still include the credential resolution path.

### 2. Schema tightened against phantom fields

`source_collector.schema.json` now sets `additionalProperties: false` at the top level and inside `prs.items`. Previously, an object with unexpected keys would pass validation silently. Now any phantom field causes the dispatch to fail with `schema_invalid` instead of proceeding with corrupt data.

### 3. JSON rescue path for residual prose contamination

A new `_rescue_json_object` helper was added to `scripts/orchestrator_runner.py`. When `json.loads` fails on the raw subagent output, dispatch falls through to this helper, which performs brace-balanced JSON extraction with string-state tracking to strip surrounding prose.

When the rescue path runs successfully, it records `prose_contamination_rescued` in the `out_reasons` list. That list is threaded through `dispatch_validated` so callers can inspect it. Without this threading fix (commit `5ee5080`), `prose_contamination_rescued` would be silently dropped and integration tests exercising the rescue path would false-green.

## Measurement Results

A 5-run Mode B re-measurement was executed after these changes. Results: **PARTIAL PASS**.

| Goal | Result |
|------|--------|
| Prose contamination in output | 0 / 5 ✅ |
| Phantom-field silent acceptance | 0 / 5 ✅ |
| Structural Category-A bypass rate | Unchanged ❌ |

The contamination and phantom-key failure modes are resolved. The structural Category-A bypass rate did not improve and is carried forward to CCE-16.

## Open Carry-Forward

**CCE-16** owns the structural Category-A bypass rate. It was not addressed here because the straightforward fix (`--bare`) was empirically confirmed to break OAuth during this investigation. CCE-16 will approach it with a different strategy.

## Integration Notes

If you write integration tests that exercise the rescue path, assert on `out_reasons` containing `prose_contamination_rescued`. A test that checks only the final parsed output will pass even if the threading is broken — the `out_reasons` assertion is the meaningful signal.

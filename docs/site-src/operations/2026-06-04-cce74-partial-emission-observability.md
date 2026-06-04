---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/99
synthesized_into: []
---

# CCE-74: Partial-Emission Observability (2026-06-04)

**PR #99** closes the observability gap where partial-reason recordings could be silently dropped from stderr. Every `docs-agent PARTIAL:` line now reaches the nightly CI artifact upload regardless of call site or dedup state.

## What changed

### `scripts/stderr_emit.py` (new)

A new stdlib-only leaf module centralises all stderr writes for the pipeline. It owns credential redaction site-wide and enforces `flush=True` on every write. No imports from `state_io` or `orchestrator_runner` are permitted — `tests/contracts/test_stderr_emit_imports.py` breaks CI immediately if you add one.

Two public functions cover the pipeline's needs: `emit_log` for diagnostic lines and `redact_credentials` for any string that might carry secrets before it reaches a log sink.

### `state_io.add_partial`

Before this change, `add_partial` only emitted the `docs-agent PARTIAL:` stderr line on the non-dedup path. A repeated reason was recorded silently. Now the emit happens on every call — including the dedup short-circuit — so the nightly CI artifact always captures the full picture of why a run went partial.

### `orchestrator_runner.py`

Three `lint_block` sites that wrote partial reasons directly now route through `add_partial`. The local `_redact_credentials` function is deleted; `stderr_emit.redact_credentials` replaces it. A new `_emit_shutdown_dump` helper is wired into the `run()` finally block so exit-0 partial runs still produce the shutdown summary on stderr. Ten raw `print(..., file=sys.stderr)` diagnostic sites are converted to `emit_log`.

### `verify_runner.py`

Two direct partial-reason writes are replaced with `add_partial` calls. The runner now participates in the same emit guarantee as the orchestrator.

## Why it matters

The CCE-41 subagent forensics work relies on the nightly CI artifact upload capturing every partial-reason. Before this PR, four call sites recorded reasons without emitting the canonical stderr line, meaning failures could be invisible to the artifact. This PR makes the invariant unconditional.

## Test coverage

Four new test files lock the eleven acceptance criteria. One existing test is extended. The full suite reports 726 passed, 3 skipped. The import-contract test in `tests/contracts/test_stderr_emit_imports.py` is the sentinel for the leaf-module isolation rule.

## No breaking changes

All existing callers of `state_io.add_partial` work without modification. The new `stderr_emit` module is additive. `orchestrator_runner` and `verify_runner` internal call sites are refactored but their public interfaces are unchanged.

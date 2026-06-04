---
title: "stderr-emit — centralized stderr and credential redaction"
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/99
synthesized_into: []
---

# stderr-emit — centralized stderr and credential redaction

`scripts/stderr_emit.py` is the single point through which every stderr write from the docs-agent pipeline flows. It is a **leaf module**: it imports only `sys` and `re` from the stdlib. It has no imports from `state_io` or `orchestrator_runner`, and CI enforces this at `tests/contracts/test_stderr_emit_imports.py`.

## Why it exists

Before CCE-74, credential redaction lived in `scripts/orchestrator_runner.py:1832-1846` (`_CREDENTIAL_URL_RE` + `_redact_credentials`), and `state_io.add_partial` only emitted the `docs-agent PARTIAL:` stderr line on the non-dedup path. Four call sites recorded partial reasons without any corresponding stderr output. The nightly CI artifact upload captures stderr to surface failure context; silent partial reasons made post-run forensics unreliable.

`stderr_emit.py` closes that gap. Every call to `state_io.add_partial` — including the dedup short-circuit path — now goes through `emit_stderr`, so the artifact contains a complete sequence of partial-reason events regardless of whether the reason is new or repeated.

## Public API

### `emit_stderr(reason, *, info_only=False)`

Writes a redacted line to stderr. The line format is:

```
docs-agent PARTIAL: <redacted reason>
docs-agent INFO: <redacted reason>   # when info_only=True
```

Pass `info_only=True` for diagnostic lines that are not partial reasons. All credential patterns matching `https?://user[:token]@host` are replaced with `<redacted>` before the line reaches stderr.

The call is best-effort: `OSError` on stderr is caught and discarded. A broken or closed stderr pipe cannot crash the orchestrator.

### `emit_log(text)`

Raw-text stderr write, no prefix and no automatic redaction. Use this for bootstrap progress and exception messages from code paths that do not involve credentials. Replaces the ten `print(..., file=sys.stderr)` calls that previously existed at `scripts/orchestrator_runner.py:643, 683, 969, 975, 981, 1493, 1498, 1503, 1508`.

If the text you are passing can contain credentials, redact it yourself with `_redact_credentials` before calling `emit_log`.

`emit_log` is also best-effort; `OSError` is swallowed.

### `_redact_credentials(text)`

Applies `_CREDENTIAL_URL_RE` (pattern: `(https?://)[^@/\s]*@`) and replaces the user segment with `<redacted>`. Idempotent. Returns the input verbatim if no credential pattern matches.

This function is not private in the calling sense — `orchestrator_runner.py` imports it directly where it needs redaction before a non-`emit_stderr` write. The underscore prefix signals "implementation constant, not a config knob."

### `_OBSERVABILITY_FLUSH`

A module-level constant set to `True`. Every `print()` inside this module passes `flush=_OBSERVABILITY_FLUSH`. The named constant prevents copy-paste from dropping `flush=True` in future edits.

`orchestrator_runner._emit_shutdown_dump` references this constant directly rather than calling `emit_stderr`, because shutdown-dump writes must propagate `OSError` rather than swallowing it.

## Call chain

```
state_io.add_partial(reason)
  └─ stderr_emit.emit_stderr(reason)          # always, including dedup path

orchestrator_runner._emit_shutdown_dump()
  └─ print(..., flush=_OBSERVABILITY_FLUSH)   # direct; OSError propagates

orchestrator_runner (diagnostic sites)
  └─ stderr_emit.emit_log(text)

verify_runner.py (partial-reason writes)
  └─ state_io.add_partial(reason)
       └─ stderr_emit.emit_stderr(reason)
```

## Invariants enforced by tests

`tests/contracts/test_stderr_emit_imports.py` parses the module's AST and fails if any import from `state_io` or `orchestrator_runner` appears. This prevents the import cycle that would break `state_io`'s role as the data layer.

Four additional test files lock the eleven acceptance criteria introduced in CCE-74. The full suite (726 passed, 3 skipped) covers: `flush=True` on every emit path, credential redaction idempotency, dedup-path stderr emission, and shutdown-dump `OSError` propagation.

## Adding a new stderr write

1. Import `emit_log` or `emit_stderr` from `scripts/stderr_emit`.
2. Use `emit_stderr` when the text is a partial reason or maps to `state_io.add_partial`.
3. Use `emit_log` for everything else. Redact credentials yourself with `_redact_credentials` before passing text in if the content can include URLs with tokens.
4. Do not call `print(..., file=sys.stderr)` directly except in `_emit_shutdown_dump`-style shutdown handlers that explicitly need `OSError` propagation.

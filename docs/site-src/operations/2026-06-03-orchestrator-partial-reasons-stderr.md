---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/93
synthesized_into: []
---

# Orchestrator partial_reasons now emit to stderr (CCE-73)

**Date:** 2026-06-03  
**Affects:** `scripts/orchestrator_runner.py` — `open_or_append_pr`, `_record_failure`, `_redact_credentials`, `run()`  
**Tickets:** CCE-73 (landed), CCE-74 (follow-up, in progress)

## What broke and why

Run ID 26766280384 — a CCE-66 post-merge verification — exited with code 1 and produced no visible output in CI logs. The run looked like a no-op.

The root cause was in `open_or_append_pr`. Six fast-fail paths collected subprocess stderr into a `partial_reasons` list but never wrote that list anywhere before exiting. Python block-buffers stdout by default; combined with process exit, every failure reason was silently discarded.

## What changed

PR #93 introduces three changes to `scripts/orchestrator_runner.py`:

**`_record_failure(reason, partial_reasons)`** appends `reason` to `partial_reasons` and immediately calls `sys.stderr.write` followed by `sys.stderr.flush()`. Flushing on each call means the reason survives even if the process exits abnormally before normal teardown.

**`_redact_credentials(text)`** strips `https://user:token@` patterns from a string before it is emitted. Any URL carrying embedded credentials is reduced to `https://<redacted>@host/...` before reaching stderr or CI logs.

**`run()`** now iterates `partial_reasons` and prints each redacted entry to stderr before returning 1. This gives you the full accumulated failure context in one place at the end of the run, in addition to the per-event flushes from `_record_failure`.

A 314-line test module covers all six fast-fail paths in `open_or_append_pr`, the redaction logic, and the final stderr dump in `run()`.

## What you see now in CI

A failed orchestrator run prints lines like:

```
[orchestrator] open_or_append_pr: gh pr create failed — exit 128
[orchestrator] open_or_append_pr: remote push rejected
```

These appear on stderr in the GitHub Actions log immediately as each failure occurs, not batched at the end.

## Follow-up: CCE-74

CCE-73 fixes only `open_or_append_pr`. There are roughly 28 other `add_partial` call sites in `run()` that still accumulate reasons silently. CCE-74 extends the same `_record_failure` pattern to all of them and folds the flush logic into `state_io.py` so new call sites get the behaviour automatically. Until CCE-74 lands, failures originating outside `open_or_append_pr` still require inspecting `.engineering-docs-agent/state.json` `partial_reasons` after the fact.

## Credential safety

`_redact_credentials` runs on every reason string before it touches stderr, CI logs, or any downstream consumer. The pattern matched is `https://username:token@` — the format GitHub Actions injects into clone URLs when `actions/checkout` is configured with a PAT. If you see `<redacted>` in a failure reason, the original URL contained embedded credentials; the redaction is working as intended.

If your team maintains a secrets-handling runbook, note that the redaction lives at `scripts/orchestrator_runner.py` in the `_redact_credentials` function. Any new credential pattern that doesn't match `user:token@` will need an explicit addition there.

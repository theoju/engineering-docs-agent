---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/93
synthesized_into: []
---

# Orchestrator stderr diagnostics

The orchestrator runner emits failure reasons to `stderr` in real time as they occur. Before PR #93 (CCE-73), all reasons were appended to `partial_reasons` in memory and never written to any stream — so when GitHub Actions killed the process after exit code 1, Python's block-buffered stdout-to-pipe discarded the accumulated buffer and operators saw only `##[error]Process completed with exit code 1` in the workflow log.

## How it works now

`_record_failure()` in `scripts/orchestrator_runner.py` replaces every silent `reasons.append()` call site (seven in total). It appends to `partial_reasons` as before, and immediately writes each reason to `sys.stderr` with `flush=True`. The flush is the critical part — it bypasses Python's line-buffering and guarantees the message lands in the Actions log before the process exits.

`run()` also emits any remaining redacted `partial_reasons` to `stderr` before returning exit code 1. This covers reasons that were accumulated before `_record_failure()` was introduced and any future paths that bypass the helper.

## Credential redaction

`_redact_credentials()` strips `https?://[^@/\s]*@` patterns from a string before it is printed or recorded. This guards against auth tokens leaking via `git push` error output — `git` can include the push URL (including embedded credentials) in its error messages. The helper is defense-in-depth; it is not a substitute for secret scanning at the workflow level.

## What you see when a run fails

Every failure reason now appears on `stderr` the moment it is recorded. If you are tailing the Actions log live, reasons surface step-by-step rather than all-at-once at exit. The `state.json` `partial_reasons` field is unchanged — the same strings land there for structured post-mortem inspection.

A typical failed run looks like:

```
[orchestrator] open_or_append_pr: branch push failed: remote: Permission denied
[orchestrator] partial run — 1 reason(s) above
```

## Test coverage

Ten `capsys`-based pytest tests cover every failure path through `_record_failure()`, the redaction invariant (no `https://token@` in captured stderr), and a happy-path counterfactual confirming `stderr` is clean on success.

## Scope and follow-up

This change is observability-only. `partial_reasons` and `state.json` semantics are unchanged — existing consumers of those fields need no updates.

CCE-74 extends `stderr` emission to all `add_partial` sites in `run()`, not just `open_or_append_pr`. That work is tracked separately and marked Done in Jira.

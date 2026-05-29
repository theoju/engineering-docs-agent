---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/62
synthesized_into: []
---

# GitHub Actions Step Summary

The orchestrator runner writes a structured digest of partial-run reasons directly to the GitHub Actions workflow summary box after every nightly run — successful or failed.

## Why this exists

`add_partial()` accumulates reasons throughout the run, but all 22 of its call-sites only mutated the in-memory state dict. Nothing reached stdout or stderr. The CCE-40 design intentionally strips `current_run` from `state.json` on disk via `save_persistent_state`, so the workflow's "Run summary" step that cats `state.json` could not surface partial reasons at all.

Operators triaging a partial or hard-failed run had to download the CCE-41 forensics artifact and grep through it. Now the digest is in the workflow summary box, no artifact download required.

## How it works

`_write_step_summary(state, repo_root)` in `scripts/orchestrator_runner.py` reads the accumulated `partial_reasons` list from the run state and appends a bulleted digest to `$GITHUB_STEP_SUMMARY` when that env var is present. GitHub Actions sets `$GITHUB_STEP_SUMMARY` automatically; the function is a no-op in local runs where the var is absent.

The function is wired inside `run()` via a `try/finally` block. The finally clause fires regardless of how `run()` exits — invalid config, corrupted state, or a crash inside `open_or_append_pr` all flush the digest before the process terminates.

## Shared digest formatter

`_format_partial_digest(partial_reasons)` is extracted from the PR body composer and reused by both surfaces. Before this change, the PR body joined partial reasons with semicolons into a single warning string. Both the step summary and the PR body now render the same bulleted list, making the two surfaces consistent.

## Known gaps

A dead-code bug exists in `.github/workflows/docs-agent-nightly.yml:123`: the `cat | sed || echo` chain fires `|| echo` only on `sed` failure, not on `cat` failure. This is out of scope for PR #62 and will be fixed in a follow-up. Post-merge manual verification of the actual `$GITHUB_STEP_SUMMARY` render via `workflow_dispatch` is still pending.

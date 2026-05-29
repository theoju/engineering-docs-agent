---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/62
synthesized_into: []
---

# Surfacing partial_reasons in GitHub Actions Step Summaries

When a nightly run is partial or fails hard, the orchestrator now writes a structured digest directly into the GitHub Actions workflow summary box — no artifact download required.

## The problem

The orchestrator's 22 `add_partial(...)` callsites only mutate in-memory state. `save_persistent_state` intentionally strips `current_run` from `state.json` on disk (CCE-40 design), so the workflow's Run-summary step that cats `state.json` sees no `partial_reasons`. Operators triaging a partial or hard-failed nightly run had to download the CCE-41 forensics artifact and grep for context.

## What changed

`_write_step_summary(state, repo_root)` is added to `scripts/orchestrator_runner.py`. It appends a bulleted digest of `partial_reasons` to `$GITHUB_STEP_SUMMARY` when the runner detects it is inside GitHub Actions. If `$GITHUB_STEP_SUMMARY` is not set (local run, CI without the env var), the function exits silently.

The call is wired via a `try/finally` block at the top of `run()`. The digest flushes on every exit path: clean success, partial completion, config-invalid abort, state-corrupted abort, and `open_or_append_pr` crash.

`_format_partial_digest(partial_reasons)` is extracted as a shared helper. The PR body composer reuses it, replacing the old semicolon-joined `WARNING: …` string with a bulleted list on both the GHA summary and PR body surfaces.

## Reading the summary

When a run has partial reasons, the workflow summary shows an entry like:

```
### Partial run — reasons

- jira_auth_missing: Jira credentials not set; jira_issues will be empty
- page_author_failed: page-author returned ok=false for docs/site-src/core/connectors.md
```

A clean run produces no partial-reasons section. You can distinguish the two cases without opening any artifact.

## OSError handling

`_write_step_summary` swallows `OSError` on write. If GitHub's summary file is unexpectedly unwritable the run does not fail because of it. The error is logged at WARNING level so it surfaces in the runner's stdout without blocking the main result.

## Test coverage

Nine tests were added in `tests/test_orchestrator_runner.py`:

- Helper contract: empty list produces empty string; populated list produces expected bullet lines.
- OSError swallowing: patching the open call to raise `OSError` does not propagate.
- Hard-fail flush: the `try/finally` path is reached even when `run()` exits via a config-invalid exception.
- Clean-path positive pin: a fully successful run with no partial_reasons produces no partial-reasons section in the summary.

## Known gap

A dead-code chain at `.github/workflows/docs-agent-nightly.yml:123` (`cat | sed || echo`) is out of scope for this change and deferred to a follow-up PR. Post-merge manual validation of the actual `$GITHUB_STEP_SUMMARY` GHA surface is still pending per the PR test plan.

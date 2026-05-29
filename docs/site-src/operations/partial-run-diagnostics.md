---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/62
synthesized_into: []
---

# Partial-run diagnostics

When the nightly pipeline runs into problems — skipped capabilities, missing auth, hard failures — the orchestrator marks the run as `partial: true` and accumulates reasons via `add_partial()`. This page explains where those reasons surface and how to read them.

## Where partial reasons appear

Partial reasons now surface in two places:

- **GitHub Actions step summary** — the workflow summary box you see when you open a run in the Actions UI.
- **PR body** — the `docs-agent/YYYY-MM-DD` PR opened (or appended to) by the nightly run.

Both surfaces use the same bulleted digest format, produced by the shared helper `scripts/orchestrator_runner.py:_format_partial_digest`.

## GitHub Actions step summary

`_write_step_summary(state, repo_root)` reads the accumulated `partial_reasons` list from the run state and appends a bulleted list to `$GITHUB_STEP_SUMMARY`. The function is called inside a `try/finally` block within `run()`, so the digest flushes even when the pipeline hard-fails (invalid config, corrupted state, or an `open_or_append_pr` crash).

Open a run in the Actions UI, click the step named after the orchestrator, and scroll to the summary box. You will see a header like **Partial run — N reason(s):** followed by one bullet per reason.

If `$GITHUB_STEP_SUMMARY` is not set (local runs, dry-run mode), `_write_step_summary` is a no-op; nothing is written and no error is raised.

## Why this change was needed

`add_partial()` only mutated the in-memory state dict. `save_persistent_state` intentionally strips `current_run` from the on-disk `state.json` (CCE-40 design), so the workflow's "Run summary" step that cats `state.json` never showed partial reasons. The only way to read them was to download the CCE-41 forensics artifact and grep through it.

Now partial reasons are readable directly in the workflow summary box with no artifact download.

## PR body digest

The PR body has always included partial warnings. Before this change, the orchestrator joined them with semicolons into a single warning line. The `_format_partial_digest` refactor upgrades that to the same bulleted list format used by the step summary. If you open the docs-agent PR and see partial reasons, the list is authoritative — it reflects every `add_partial()` call that completed before the PR was opened or updated.

## Triage workflow

1. Open the failed or partial run in the GitHub Actions UI.
2. Read the step summary digest. Each bullet identifies the capability or stage that triggered `add_partial()` and a short reason string.
3. Common reasons map to known root causes:
   - `jira_auth_missing` — `JIRA_EMAIL` or `JIRA_API_TOKEN` is not set in repo secrets.
   - `source_collector_error` — the source-collector subagent returned a non-zero exit or malformed JSON.
   - `no_prs_in_window` — no merged PRs were found between the last successful SHA and HEAD; the run is partial but expected.
4. For reasons not listed here, check the CCE-41 forensics artifact (`docs-agent-diagnostics-*.tar.gz`) attached to the run. The artifact contains the full `current_run.json` and subagent stdout/stderr.

## Known limitation

A dead-code bug exists in `.github/workflows/docs-agent-nightly.yml:123`: the `cat | sed || echo` chain fires the fallback only on `sed` failure, not on `cat` failure. This is tracked as a follow-up and does not affect the partial-reasons digest path.

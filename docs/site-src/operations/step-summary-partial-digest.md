---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/62
synthesized_into: []
---

# Step Summary: Partial-Digest Output

When the orchestrator runs inside GitHub Actions, it writes a structured digest of `partial_reasons` to `$GITHUB_STEP_SUMMARY`. The summary appears in the workflow run's **Summary** tab immediately after the job completes — no artifact download required.

## How it works

The runner calls `_write_step_summary(state, repo_root)` from a `try/finally` block inside `run()`. The `finally` placement is deliberate: the digest flushes even when the run terminates on a hard-fail path — invalid config, corrupted state, or a crash inside `open_or_append_pr`.

`_write_step_summary` delegates formatting to `_format_partial_digest(partial_reasons)`, which converts the list of reason strings into a Markdown bulleted list. The same helper is called by the PR body composer, so both surfaces — the workflow summary box and the docs-agent PR body — render identical, human-readable bullets instead of the previous semicolon-joined warning string.

## `$GITHUB_STEP_SUMMARY` contract

The runner appends to the file path in `$GITHUB_STEP_SUMMARY`. If the env var is unset (local runs, dry-run mode, non-Actions CI), `_write_step_summary` exits immediately without writing anything. There is no fallback write target and no error is raised.

The written content is a Markdown fragment — a `## Partial run reasons` heading followed by a bulleted list. GitHub Actions renders this inline in the job summary UI.

## No-op behaviour outside GitHub Actions

You can invoke the orchestrator locally (`python3 scripts/orchestrator_runner.py --repo-root . --no-pr`) without setting `$GITHUB_STEP_SUMMARY`. The helper detects the missing env var and skips the write. `partial_reasons` are still persisted to `.engineering-docs-agent/state.json` and surfaced in the forensics artifact for local triage.

## Triage guide

When a nightly run is partial or hard-failed, open the GitHub Actions run and click **Summary**. The digest lists every reason the run was degraded, in the order the runner encountered them. Common entries:

- `jira_auth_missing` — Jira enrichment skipped; set `JIRA_EMAIL` and `JIRA_API_TOKEN` repo secrets.
- `subagent_error:<agent>` — a subagent returned a non-zero exit or malformed JSON; check the per-agent log in the `DOCS_AGENT_DEBUG_DIR` artifact.
- `no_prs_in_window` — the source-collector found zero merged PRs in the run window; verify `last_successful_run.head_sha` in `.engineering-docs-agent/state.json` is not stale.

The PR body (opened or appended to by `open_or_append_pr`) carries the same bulleted list under a **Partial run** callout, so reviewers see the same information without opening the Actions UI.

## Dual-surface helper

`_format_partial_digest` is a shared formatting contract. If you change its output format, both the step-summary and the PR body change together. Keep that coupling in mind before editing the helper — its callers are `_write_step_summary` and the PR body composer inside `scripts/orchestrator_runner.py`.

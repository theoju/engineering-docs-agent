---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/62
synthesized_into: []
---

# Step summary observability

When a nightly run encounters a partial or hard-failed subagent, the runner writes a formatted digest to GitHub Actions' built-in step summary. You can read this digest directly in the workflow run UI without downloading any forensics artifact.

## What the runner writes

`_write_step_summary` in `scripts/orchestrator_runner.py:_write_step_summary` appends a `## docs-agent partial_reasons` section to `$GITHUB_STEP_SUMMARY` at the end of every run. It is called inside the `finally` block at `scripts/orchestrator_runner.py:run`, so it fires whether the run exits cleanly or raises.

The section lists every entry in `state["current_run"]["partial_reasons"]` — one bullet per reason. Entries accumulate across the run's 22 `add_partial` call sites: subagent dispatch failures, lint blocks, source-collector errors, citation-drift failures, and more.

The format is produced by `_format_partial_digest` at `scripts/orchestrator_runner.py:_format_partial_digest`. That same helper is used by the PR body composer in `open_or_append_pr`, so the step summary and the PR body show identical reason strings.

## When the digest is suppressed

`_write_step_summary` is a no-op in three cases:

- `$GITHUB_STEP_SUMMARY` is not set. Local runs and unit tests hit this path every time — no file is written, no error is raised.
- `state["current_run"]` is absent or has no `partial_reasons` key.
- `partial_reasons` is an empty list (a fully-clean run).

Write failures (unwritable path, missing parent directory) are swallowed silently. The runner treats diagnostics as best-effort; the primary job is producing docs.

## How to use it during triage

1. Open the failing workflow run in GitHub Actions.
2. Click the run's **Summary** tab (not the job log).
3. Scroll to the **docs-agent partial_reasons** section.

Each bullet identifies the failure stage and a short reason string. Common prefixes and their meaning:

| Prefix | Stage |
|---|---|
| `source_collector_error` | Source-collector subagent returned an error field |
| `pr_summarizer_invalid` | PR-summarizer returned `None` or failed schema validation |
| `page_author_invalid` | Page-author returned `None` or failed schema validation |
| `lint_block` | Content-validator blocked a page at `severity: block` |
| `gap_detector_invalid` | Gap-detector returned `None` |
| `verify_citations_failed` | Citation-drift stage threw an exception (advisory, run continued) |
| `source_map_failed` | Source-drift stage threw an exception (advisory, run continued) |

For deeper investigation — per-subagent prompt, stdout, stderr, and stream files — use the forensics artifact uploaded by the nightly workflow (see CCE-41). The step summary gives you the reason string; the forensics artifact gives you the full LLM exchange.

## Relation to `state.json`

`save_persistent_state` (called from `scripts/orchestrator_runner.py:run`) strips `current_run` from the on-disk `state.json` before committing. `partial_reasons` therefore never persists to the docs-agent branch. The step summary is the only durable first-class signal for reasons from a specific run; the forensics artifact is the only way to reconstruct the full subagent context after the runner exits.

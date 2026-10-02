---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/62
  - https://github.com/theoju/engineering-docs-agent/pull/285
synthesized_into: []
---

# Step summary observability

When a nightly run encounters a partial or hard-failed subagent, the runner writes a formatted digest to GitHub Actions' built-in step summary. You can read this digest directly in the workflow run UI without downloading any forensics artifact.

## What the runner writes

`_write_step_summary` in `scripts/orchestrator_runner.py:_write_step_summary` appends a `## docs-agent partial_reasons` section to `$GITHUB_STEP_SUMMARY` at the end of every run. It is called inside the `finally` block at `scripts/orchestrator_runner.py`, so it fires whether the run exits cleanly or raises.

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

| Prefix                         | Stage                                                                                                       |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| `source_collector_error`       | Source-collector subagent returned an error field                                                           |
| `pr_summarizer_invalid`        | PR-summarizer returned `None` or failed schema validation                                                   |
| `page_author_invalid`          | Page-author returned `None` or failed schema validation                                                     |
| `lint_block`                   | Content-validator blocked a page at `severity: block`                                                       |
| `gap_detector_invalid`         | Gap-detector returned `None`                                                                                |
| `verify_citations_failed`      | Citation-drift stage threw an exception (advisory, run continued)                                           |
| `source_map_failed`            | Source-drift stage threw an exception (advisory, run continued)                                             |
| `output_token_limit_truncated` | Subagent's answer crossed the CLI output-token ceiling and was refused unparsed (blind at source-collector) |

`output_token_limit_truncated` names a subagent answer the CLI split across two assistant messages after hitting its 64,000-output-token ceiling. Only the second half reaches the orchestrator, so the captured payload is known-incomplete and is refused rather than parsed — a fragment that happened to parse would be accepted as the whole answer and the watermark would advance past changes the run never documented. At the source-collector call site the reason is **blind**: the run exits non-zero and the baseline stays put, so nothing is silently skipped.

**What to do:** re-run the nightly. The trigger is how verbosely the subagent transcribes each `body` and `description`, which varies run to run on identical input, so a re-run usually clears it. If it repeats, the per-field character budget in `agents/source-collector.md` (Steps 3 and 5) is too loose for the window and should be tightened.

### Source-collector output budget and failure payload (CCE-177)

Three nightlies (09-18, 09-20, 09-23) failed with `schema_invalid: source-collector: 'prs' is a required property`. The agent's answer was correct but about 160KB, so the CLI hit its output-token ceiling mid-object and the model finished the JSON in a second assistant message. Only the last message was kept, so the fragment had no `prs` key. The run was classified blind, exited 1, and froze the watermark.

Two changes keep that signature unambiguous:

- **The agent bounds its own output.** `agents/source-collector.md` caps each `prs[].body` and `jira_issues[].description` at 1,000 characters in total, marker included: a cut value ends in `…[truncated]`. This is an instruction, not a schema `maxLength` — a schema can only reject what the agent already emitted, and a blind `schema_invalid` would turn a sometimes-failure into a nightly one. The cap bounds each value, not the number of linked Jira issues, so a very large window can still reach the ceiling.
- **The documented failure payload is schema-valid.** On unrecoverable Git failure the agent now returns `{"prs": [], "jira_issues": [], "partial": true, "error": "git_unrecoverable: <reason>"}`. The old `{"error": ...}` shape also produced `'prs' is a required property`, which made a real Git failure indistinguishable from a truncated answer. A source-collector failure now reaches the digest with its reason attached.

If the ceiling is crossed anyway, you see `output_token_limit_truncated: source-collector` rather than the `'prs'` error. That is the detector working, not a regression.

The detector only runs when `DOCS_AGENT_DEBUG_DIR` is set, because the event stream exists only in that mode. Hosts without it get the output budget but no split detection.

For deeper investigation — per-subagent prompt, stdout, stderr, and stream files — use the forensics artifact uploaded by the nightly workflow (see CCE-41). The step summary gives you the reason string; the forensics artifact gives you the full LLM exchange.

## Relation to `state.json`

`save_persistent_state` (called from `scripts/orchestrator_runner.py`) strips `current_run` from the on-disk `state.json` before committing. `partial_reasons` therefore never persists to the docs-agent branch. The step summary is the only durable first-class signal for reasons from a specific run; the forensics artifact is the only way to reconstruct the full subagent context after the runner exits.

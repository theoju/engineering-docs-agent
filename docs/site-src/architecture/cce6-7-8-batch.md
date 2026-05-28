---
description: Dispatch layer and orchestrator run-loop introduced in the CCE-6/7/8 batch
source_files:
  - scripts/dispatch_subagent.py
  - scripts/orchestrator_runner.py
last_reviewed: '2026-05-28'
status: draft
---

# CCE-6 / 7 / 8 Batch: Dispatch and Orchestration Layer

The CCE-6/7/8 batch landed the core dispatch infrastructure and the orchestrator run-loop that drives every nightly docs-PR. These changes are the spine of the pipeline: every subsequent capability (gap detection, page authoring, notifier) runs through the patterns established here.

## Subagent dispatch

`dispatch_subagent` in `scripts/orchestrator_runner.py` is the single call point for every agent invocation. It wraps the agent's JSON payload in **execution framing** — a preamble that tells the Claude CLI to execute the agent's job rather than analyze the JSON as content (CCE-3 A).

Two paths depending on context:

- **Dry-run mode** (`dry_run_dir` set): reads a fixture from `<dir>/fake_<agent_name>.json` instead of spawning a process. All unit tests use this path.
- **Production mode**: spawns `claude -p <prompt> --agent <name> --plugin-dir <root>` with `--setting-sources project,local` to skip user-level plugins that inject prose into stdout (CCE-15).

The `--allowedTools` flag is populated from the `tools:` YAML frontmatter in `agents/<name>.md` when present (`orchestrator_runner.py:68` → `_load_agent_allowed_tools`). Agents that declare no tools get no `--allowedTools` argument.

The subprocess always receives `CLAUDE_STOP_VERIFY=0` in its environment (CCE-10). Without this, a global `stop-verify` shell hook contaminates stdout with a prose preamble that breaks `json.loads`.

## Validated dispatch

`dispatch_validated` composes `dispatch_subagent` with `contracts.validate_and_parse` (`orchestrator_runner.py:486`). Prefer `dispatch_validated` over raw `dispatch_subagent` at every call site; it returns `(dict | None, list[str])` — the parsed output and any partial reasons to forward to `add_partial`.

| Return | Meaning |
|---|---|
| `(dict, [])` | Schema-valid output |
| `(dict, ["prose_contamination_rescued: <name>"])` | Valid after CCE-15 rescue |
| `(None, reasons)` | Schema-invalid |
| `(None, [])` | Dispatch returned None — caller adds its own reason |
| `(None, ["schema_missing: <name>"])` | No JSON schema found for agent |

## Prose contamination recovery

`_rescue_json_object` (`orchestrator_runner.py:128`) scans stdout for the first balanced JSON object when strict `json.loads` fails. It handles the CCE-15 pattern where a Claude-level plugin injects a prose preamble (e.g. "★ Insight") before the JSON output.

When rescue succeeds, `"prose_contamination_rescued: <name>"` lands in `partial_reasons` so the event is visible in state and Slack/email notifications. The `--setting-sources project,local` flag closes the primary contamination pathway, but the rescue stays as defense in depth.

## Debug artifacts

Set `DOCS_AGENT_DEBUG_DIR` to a directory path before running the orchestrator. Each dispatch writes:

| File | Contents |
|---|---|
| `<ts>-<agent>.prompt.txt` | Verbatim prompt sent to Claude |
| `<ts>-<agent>.stdout.txt` | Extracted canonical JSON (caller view) |
| `<ts>-<agent>.stream.jsonl` | Raw NDJSON event stream |
| `<ts>-<agent>.meta.json` | Return code, argv, and tool-use summary |

In debug mode the CLI runs with `--output-format stream-json --verbose`. `_extract_final_assistant_text` (`orchestrator_runner.py:175`) extracts the final assistant turn's concatenated text content, skipping turns that are tool-use only (CCE-14). `_summarize_tool_use` (`orchestrator_runner.py:208`) produces the `tool_use` block in `meta.json`, capped at 50 entries.

Leave `DOCS_AGENT_DEBUG_DIR` unset in steady-state production. Stream-json mode adds per-invocation latency that scales with tool-call count; the CCE-12 baseline measured 3–6 s for zero-tool-call runs versus 74 s for a five-call outlier.

## Orchestrator run loop

The `run` function (`orchestrator_runner.py:801`) executes the nightly pipeline in this order:

1. Load config (`load_config_validated`) and state (`load_state_validated`); rotate `current_run` — partial reasons from the prior run are dropped rather than carried forward (CCE-5).
2. Dispatch `source-collector` to fetch PRs and Jira issues.
3. Clip the PR list to the `last_sha..head_sha` git window via `_clip_prs_to_window` (CCE-19 safety net — the agent prompt was observed to return out-of-window PRs in 3/5 baseline runs).
4. Dispatch `pr-summarizer` for each PR; accumulate `summaries`.
5. Batch `doc_targets` per `(lens, page_hint)` pair and dispatch `page-author` for each batch.
6. Dispatch `content-validator` on authored paths; roll back files whose failures have `severity: block`.
7. Regenerate archive indexes for lenses that have `archive_index: true`.
8. Compute source drift (M), citation drift (C1), and canonical-core drift (C2).
9. Dispatch `gap-detector` for each PR not in the dismissed-flags set.
10. Prepend a What's New entry with PR summaries, gap flags, and drift sections.
11. Open or append the docs-agent PR (`open_or_append_pr`).
12. Dispatch `notifier` with the run digest.

A partial failure at any stage sets `state['current_run']['partial'] = True` and appends a reason string, but execution continues to the next stage. A failed page-author does not abort gap detection; a failed gap-detector does not abort the PR open.

## Bootstrap entry (C2 core pages)

`run_bootstrap_core` (`orchestrator_runner.py:1251`) is a separate entry point invoked with `--bootstrap-core`. It reads `<docs_dir>/.doc-core-manifest.json`, authors each declared page that has no file yet via `page-author`, and prints a JSON ledger. It is idempotent: existing files are skipped without touching them.

The dry-run path calls `_synthesize_core_page` (`orchestrator_runner.py:563`) to write a frontmatter + skeleton body without invoking Claude, so tests exercise the full manifest-walk without API cost.

## Gotchas & layering rules

The `_page_target_is_editable` check (`orchestrator_runner.py:522`) runs twice — once in the nightly authoring loop and once in `run_bootstrap_core`. Both checks are required; removing either opens a path for the agent to write outside `agent_editable_paths`.

`load_state_validated` and `load_config_validated` raise typed exceptions (`StateError`, `ConfigError`). Catch them at the top of `run` and `run_bootstrap_core`; do not let them propagate to the CLI entry point or the exit code becomes unpredictable.

The `GITHUB_REPOSITORY` env var takes precedence over git-remote detection in `detect_repo` (`orchestrator_runner.py:28`). In GitHub Actions the var is always set; locally you may see `owner: unknown` if the remote URL format is non-standard.

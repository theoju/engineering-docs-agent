---
description: "Stream-json dispatch mode that captures the exact tool-call sequence\
  \ each subagent executes at runtime, gated by `DOCS_AGENT_DEBUG_DIR` \u2014 built\
  \ to diagnose the 10\u201320\xD7 per-run latency variance in source-collector."
source_files:
- docs/superpowers/measurements/2026-05-20-cce12-run[1-5]-*.{stream.jsonl,meta.json,stdout.txt,stderr.txt,prompt.txt}
- scripts/orchestrator_runner.py
- tests/orchestrator/test_dispatch_subagent_stream_json.py
last_reviewed: '2026-05-28'
status: draft
doc_kind: architecture
---

# CCE-12: Source-Collector Tool-Use Diagnostics

CCE-12 added stream-json dispatch mode to `dispatch_subagent` so you can observe the exact tool-call sequence a subagent executes at runtime. The primary motivation was diagnosing why the source-collector agent's latency varied by 10–20× across runs — and confirming whether that variance was driven by tool calls or by the NDJSON parse overhead.

## How diagnostic mode activates

Set `DOCS_AGENT_DEBUG_DIR` to any writable directory before invoking the orchestrator:

```bash
export DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

When `debug_dir` is truthy, `dispatch_subagent` switches from `--print` to `--output-format stream-json --verbose` (`orchestrator_runner.py:407`). The raw NDJSON event stream is consumed in-process, not piped through a file.

## Forensics artifacts

Each dispatch run writes five files to `DOCS_AGENT_DEBUG_DIR`:

| Suffix          | Contents                                               |
| --------------- | ------------------------------------------------------ |
| `.prompt.txt`   | Exact prompt passed to `claude -p`                     |
| `.stdout.txt`   | Canonical JSON extracted from the final assistant turn |
| `.stderr.txt`   | Raw stderr from the `claude` subprocess                |
| `.stream.jsonl` | Full NDJSON event stream (one event per line)          |
| `.meta.json`    | Return code, argv, and `tool_use` summary block        |

Files are named `<UTC-timestamp>-<agent-name>.<suffix>` so multiple runs don't clobber each other. The `.stdout.txt` holds the caller-visible canonical JSON — the same text `dispatch_subagent` returns to the orchestrator — so you can diff it against the full stream without knowing which dispatch path produced it.

## Extracting the canonical JSON

The final assistant turn may contain interleaved `tool_use` and `text` blocks. `_extract_final_assistant_text` (`orchestrator_runner.py:175`) concatenates only the `text` blocks from the **last** assistant message that contains at least one text block.

This is a forward-compatibility guard added in CCE-14: if the model ends on a purely tool-use turn (no text), the function walks backward to the preceding assistant turn rather than returning an empty string. Tests in `test_dispatch_subagent_stream_json.py:42` and `:63` cover both the multi-block concatenation and the last-assistant-only selection.

## Tool-use summary

`_summarize_tool_use` (`orchestrator_runner.py:208`) makes two passes over the event list:

1. Collect `tool_result` blocks from `user` events, keyed by `tool_use_id`, to capture `is_error` and `result_chars`.
2. Collect `tool_use` blocks from `assistant` events and join with the outcomes from pass 1.

The output written to `.meta.json` includes:

- `total_calls` — total tool invocations across all turns
- `by_name` — per-tool call counts (e.g. `{"Bash": 2}`)
- `calls` — list of `{name, input_preview, is_error, result_chars}`, capped at 50
- `calls_truncated` — true if more than 50 calls were made
- `turns`, `stop_reason`, `duration_ms` — from the terminal `result` event

The 50-call cap keeps `.meta.json` compact on chatty runs. `calls_truncated` signals when the cap engaged; the `.stream.jsonl` retains the full record.

## Baseline measurements (CCE-12 runs 1–5)

The five runs on 2026-05-20 split into two categories:

**Category A — zero tool calls (runs 1, 3, 4, 5):** end-to-end latency 3–6 s. The agent returned a JSON answer directly from its prompt without invoking `Bash` or any other tool.

**Category B — active tool calls (run 2):** 74 s. Run 2 made 5 `Bash` calls (`gh pr list`, `gh api` variants) before emitting the final JSON. The entire latency delta is attributable to tool-call round-trips, not NDJSON parse overhead.

Conclusion: stream-json dispatch mode is appropriate for diagnostic measurement. Leave `DOCS_AGENT_DEBUG_DIR` unset in steady-state production to run the faster `--print` path.

## Related hardening

Several fixes landed alongside or shortly after CCE-12 that affect dispatch reliability:

- **CCE-10** — `CLAUDE_STOP_VERIFY=0` is injected into the subprocess environment (`orchestrator_runner.py:419`) to prevent a global stop-verify hook from prepending prose to the agent's stdout and breaking `json.loads`.
- **CCE-15** — `--setting-sources project,local` (`orchestrator_runner.py:393`) excludes the user-level settings.json where an explanatory-output-style plugin was injecting `★ Insight` preambles into subprocess context. This closed the contamination pathway that broke Run 4's output parsing in CCE-14.
- **CCE-15 rescue path** — `_rescue_json_object` (`orchestrator_runner.py:128`) is a defense-in-depth fallback that extracts the first balanced JSON object from prose-contaminated output when `json.loads` fails on the canonical text.

## Tests

`tests/orchestrator/test_dispatch_subagent_stream_json.py` covers the stream-json path against NDJSON fixtures in `tests/orchestrator/fixtures/cce12_stream_json/`:

- `test_extract_final_assistant_text_with_tools_fixture` — fixture with interleaved tool calls; asserts the final parsed JSON.
- `test_extract_final_assistant_text_no_assistant_returns_empty` — no assistant events → empty string.
- `test_extract_final_assistant_text_concatenates_multi_text_blocks` — text blocks split around a tool_use block are joined.
- `test_extract_final_assistant_text_uses_last_assistant_only` — second assistant message wins over first.
- `test_summarize_tool_use_with_tools_fixture` — asserts `total_calls`, `by_name`, `stop_reason`, `duration_ms`, first call's `input_preview`.
- `test_summarize_tool_use_no_tools_fixture` — zero-call run produces empty summary.
- `test_summarize_tool_use_flags_errored_tool_result` — `is_error: true` propagates from `tool_result` block.
- `test_summarize_tool_use_caps_calls_at_50_and_sets_truncated` — 51 calls → `calls_truncated: true`, `calls` list length 50.

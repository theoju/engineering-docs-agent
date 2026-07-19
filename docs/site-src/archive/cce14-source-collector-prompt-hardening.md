---
description: "Investigation of why source-collector output parsing failed in baseline\
  \ runs, using CCE-12's stream-json diagnostics to isolate two root causes \u2014\
  \ `_extract_final_assistant_text` returning empty on tool-use-only final turns,\
  \ and SessionStart-hook prose contamination."
source_files:
- scripts/orchestrator_runner.py
- tests/orchestrator/test_dispatch_debug_capture.py
- tests/orchestrator/test_dispatch_subagent_stream_json.py
last_reviewed: '2026-05-28'
status: draft
doc_kind: decision
sources: []
synthesized_into: []
---

# CCE-14: Source Collector Prompt Hardening

CCE-14 investigated why source-collector output parsing failed in baseline runs. The investigation used stream-json diagnostics (built in CCE-12) to observe ground-truth tool-call sequences. It identified two root causes: `_extract_final_assistant_text` returning `""` when the model's final assistant turn contained only `tool_use` blocks, and a user-level plugin's `SessionStart` hook injecting "★ Insight" prose before the JSON output (addressed as CCE-15).

## Stream-json diagnostics

Set `DOCS_AGENT_DEBUG_DIR` to any writable path before running the orchestrator to enable stream-json dispatch mode. The dispatcher switches from its default `--output-format` (simple print) to `--output-format stream-json --verbose`.

Five forensics artifacts are written per agent dispatch:

- `<timestamp>-<agent>.prompt.txt` — the full prompt sent to Claude
- `<timestamp>-<agent>.stdout.txt` — the extracted canonical JSON (the caller's view)
- `<timestamp>-<agent>.stderr.txt` — raw stderr
- `<timestamp>-<agent>.stream.jsonl` — raw NDJSON event stream
- `<timestamp>-<agent>.meta.json` — returncode, argv, and tool_use summary

The `tool_use` block in `meta.json` includes total call count, per-tool breakdown, turn count, stop reason, and duration in milliseconds. This is the primary diagnostic surface for understanding what the agent actually did vs. what its prompt asked it to do.

Per-run latency in stream-json mode is dominated by the agent's tool-call decisions, not NDJSON parse overhead. CCE-12 measured 3–6 s for zero-tool-call runs vs. 74 s for a run that made five tool calls. Leave `DOCS_AGENT_DEBUG_DIR` unset in steady-state production.

Implementation: `scripts/orchestrator_runner.py:_last_processed_merge_sha`.

## `_extract_final_assistant_text` hardening

The prior implementation returned text from the last assistant message. If that message contained only `tool_use` blocks and no `text` blocks, the function returned `""` — even when an earlier assistant turn held the correct answer.

CCE-14 hardened `_extract_final_assistant_text` (`scripts/orchestrator_runner.py:_rescue_json_object`) to walk all assistant events and track the last one that has at least one `text` block. The function concatenates all text blocks from that turn, skipping any trailing purely-`tool_use` turns.

Two distinct cases are handled:

- **Last turn is pure tool_use, earlier turn has text** → return the earlier turn's text.
- **Every assistant turn is pure tool_use** → return `""`.

Concatenation handles turns where the model interleaves `tool_use` and `text` blocks within a single assistant message; only `text`-typed blocks contribute to the result.

Tests covering these cases: `test_extract_final_assistant_text_skips_pure_tool_use_final_turn` and `test_extract_final_assistant_text_all_tool_only_returns_empty` in `tests/orchestrator/test_dispatch_subagent_stream_json.py:test_extract_final_assistant_text_skips_pure_tool_use_final_turn`.

## Plugin contamination (CCE-14 Run 4 → CCE-15)

CCE-14 Run 4 surfaced a second failure mode: the user-level `explanatory-output-style` plugin's `SessionStart` hook injected an "★ Insight" preamble before the subagent's JSON output. `json.loads()` on the contaminated stdout raised `JSONDecodeError`.

CCE-15 added two mitigations, both in `scripts/orchestrator_runner.py`.

**`--setting-sources project,local`** (`scripts/orchestrator_runner.py:_order_prs_oldest_first`): every `claude` subprocess receives this flag, which skips the user-level `settings.json` where the plugin is enabled. OAuth and keychain authentication are preserved — unlike `--bare`, this flag does not strip credentials.

**`_rescue_json_object`** (`scripts/orchestrator_runner.py`): a prose-tolerant rescue path invoked when strict `json.loads()` fails. The function locates the first `{`, scans forward tracking brace depth while honoring JSON string state (escaped characters, quoted strings), and attempts `json.loads()` on the balanced slice. On success it records `prose_contamination_rescued: <agent>` in `partial_reasons` so the event appears in state and in Slack/email notifications.

The `--setting-sources` flag closes the SessionStart-hook contamination pathway. `_rescue_json_object` handles other contamination patterns that may emerge.

## `_summarize_tool_use`

`_summarize_tool_use` (`scripts/orchestrator_runner.py:_strip_code_fence`) produces the `tool_use` block written to `meta.json` in stream-json mode.

Two-pass algorithm:

1. Walk `user` events and collect `tool_result` outcomes keyed by `tool_use_id`, recording `is_error` and `result_chars`.
2. Walk `assistant` events and collect `tool_use` blocks; join with pass-1 outcomes so each call carries its error flag and result character count.

The `calls` list is capped at 50 to keep `meta.json` compact on chatty runs; `calls_truncated` flips to `true` when the cap engages. Run-level fields (`turns`, `stop_reason`, `duration_ms`) come from the terminal `result` event.

## Test coverage

`tests/orchestrator/test_dispatch_subagent_stream_json.py` covers:

- `_extract_final_assistant_text` with a fixture NDJSON stream containing two Bash tool calls and a final text turn.
- Multi-block text concatenation: interleaved `text` and `tool_use` blocks in a single assistant message.
- Pure-tool_use final turn hardening (CCE-14 core case).
- All tool_use, no text in any turn (CCE-14 coverage gap from Stage 4 review).
- `_summarize_tool_use` with the same fixture: total calls, per-name breakdown, error flags, 50-call truncation cap.
- Full dispatch integration: stream-json argv flags, 5-artifact write, `stdout.txt` holds extracted JSON (not raw NDJSON), `meta.json` carries the `tool_use` block.

`tests/orchestrator/test_dispatch_debug_capture.py` covers:

- Non-NDJSON stdout handled gracefully in stream-json mode: returns `None`, writes all five artifacts for forensics.
- `DOCS_AGENT_DEBUG_DIR` unset → simple-print path, no artifacts written.

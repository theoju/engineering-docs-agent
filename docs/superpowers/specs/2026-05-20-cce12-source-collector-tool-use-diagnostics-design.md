# CCE-12: Source-Collector Tool-Use Diagnostics — Design

**Status:** Draft for review
**Jira:** [CCE-12](https://designitright.atlassian.net/browse/CCE-12)
**Parent:** Split from CCE-10 (F2 follow-up after canonical-shape ceremony passed)
**Branch:** `feat/CCE-12-source-collector-tool-use-diagnostics`

## Problem

The CCE-10 5-run Mode B ceremony confirmed the source-collector subagent reliably emits the canonical `{"prs": [...], "jira_issues": [...]}` shape. But the _content_ told a second story:

- Runs 1–4: empty `prs: []` and `jira_issues: []`
- Run 5: 3 real `jira_issues` (CCE-10/11/12) with full metadata

The dispatch window for every run was identical (`last_sha=1f4563c2..head_sha=5d0470b`, ~9 merged PRs available, `--allowedTools` grants `Bash Read Write Edit WebFetch`). The agent provably **can** call its tools — Run 5 returned real data. It just **doesn't** most of the time.

We have no visibility into why. The subprocess stdout is the final JSON only. The agent's internal turn-by-turn behavior — whether it called `gh`, whether the call failed, whether it called something else, whether it skipped tools entirely — is invisible to the orchestrator.

CCE-12 is the diagnostic that closes that visibility gap. The fix for whatever pattern dominates is a separate ticket — this one ships the instrument, not the cure.

## Goals

1. Capture the source-collector subagent's **complete tool-call sequence** on every Mode B dispatch (when diagnostics are enabled).
2. Persist a structured summary alongside the existing CCE-9 debug artifacts.
3. Make the data legible enough that we can categorize each run into root-cause buckets (skipped tools / called and discarded / legitimately empty / errored).
4. Preserve the existing dispatch contract: the orchestrator caller still sees `subprocess.stdout` as the canonical JSON. Zero downstream change.
5. Re-run the CCE-10 5-run ceremony with diagnostics on and produce a measurement document with the per-run categorization.

## Non-goals

- Fixing the underlying tool-avoidance behavior. CCE-12 is observation only.
- Making stream-json the production default. Diagnostics are gated; production path is unchanged.
- Migrating other subagents to stream-json as a primary path. They inherit the diagnostic for free when the gate is on, but we're not redesigning their dispatch.
- Per-agent tool-use budgets, circuit breakers, or retry-on-no-tool-calls. All deferred.

## Approach

Use `claude -p ... --output-format stream-json --verbose --agent <name>` for subagent dispatches when `DOCS_AGENT_DEBUG_DIR` is set. Parse the NDJSON event stream in `dispatch_subagent`, extract the final assistant text content as the synthetic "stdout" returned to callers, and compute a tool-use summary that gets folded into the existing `<agent>.meta.json` written by CCE-9's diagnostic capture.

When the gate is off, `dispatch_subagent` runs the existing simple `--print` path unchanged. Production is unaffected.

### Why orchestrator-side instrumentation

The natural temptation is to add a Procedure step to `agents/source-collector.md` asking the agent to self-report its tool calls. We are explicitly **not** doing this. The agent under measurement is the one suspected of misbehaving — its self-reports are precisely the data we cannot trust. Instrumentation lives in the dispatcher so it observes ground truth.

### Why gate on `DOCS_AGENT_DEBUG_DIR`

CCE-9 already established this env var as the diagnostic-capture switch. Re-using it:

- One mental model for operators.
- No new config surface.
- Stream-json overhead (~10–20% latency from NDJSON parsing) only paid when diagnostics are on.
- When unset, the dispatcher is byte-for-byte the same as today.

## Architecture

```
dispatch_subagent(agent_name, prompt, ...)
  │
  ├─ debug_dir = os.environ.get("DOCS_AGENT_DEBUG_DIR")
  │
  ├─ if not debug_dir:
  │     run existing simple --print path
  │     return CompletedProcess (stdout = canonical JSON)
  │
  └─ if debug_dir:
        cmd = [..., "--output-format", "stream-json", "--verbose"]
        proc = subprocess.run(cmd, capture_output=True, ...)

        # parse NDJSON, extract canonical JSON + summary
        events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        final_text = _extract_final_assistant_text(events)
        summary    = _summarize_tool_use(events)

        # persistence — semantics held constant with the simple-print path:
        #   <agent>.stdout.txt = what the caller received (extracted final text)
        #   <agent>.stream.jsonl = raw NDJSON event stream (stream-json only)
        write final_text        → debug_dir/<agent>.stdout.txt    (canonical JSON, caller view)
        write proc.stdout       → debug_dir/<agent>.stream.jsonl  (raw NDJSON, forensics)
        write proc.stderr       → debug_dir/<agent>.stderr.txt    (CCE-9 already does this)
        write prompt            → debug_dir/<agent>.prompt.txt    (CCE-9 already does this)

        # extend CCE-9's meta.json with the tool_use block
        meta = {..., "tool_use": summary}
        write meta              → debug_dir/<agent>.meta.json

        # caller contract: stdout is still the canonical JSON
        return CompletedProcess with stdout=final_text, stderr=proc.stderr
```

## Stream-json parsing rules

The Claude Code CLI emits NDJSON events with at least these types we care about:

- `system` — session init metadata (model, cwd, tools, mcp_servers). Captured raw; not summarized.
- `assistant` — model turn. `message.content` is a list of content blocks. We inspect blocks of type `text` (concatenated for final-text extraction) and `tool_use` (counted/summarized).
- `user` — tool-result return. `message.content` contains `tool_result` blocks with `is_error` and `content` fields. Used to flag failed tool calls.
- `result` — terminal session summary. Contains `stop_reason`, `duration_ms`, `total_cost_usd`, `num_turns`. Used to populate the summary's run-level fields.

### Final-text extraction

```python
def _extract_final_assistant_text(events: list[dict]) -> str:
    """Concatenate all text blocks from the LAST assistant message.

    The orchestrator's downstream contract is that stdout = canonical JSON.
    In stream-json mode the canonical JSON is the text content of the final
    assistant turn — possibly split across multiple text blocks if the model
    interleaved tool_use blocks before its final answer.
    """
    last_assistant = None
    for ev in events:
        if ev.get("type") == "assistant":
            last_assistant = ev
    if last_assistant is None:
        return ""
    content = last_assistant.get("message", {}).get("content", [])
    return "".join(
        block.get("text", "")
        for block in content
        if block.get("type") == "text"
    )
```

### Tool-use summary

```python
def _summarize_tool_use(events: list[dict]) -> dict:
    calls: list[dict] = []
    errors_by_id: dict[str, bool] = {}
    result_chars_by_id: dict[str, int] = {}

    # First pass: collect tool_result outcomes by tool_use_id
    for ev in events:
        if ev.get("type") != "user":
            continue
        for block in ev.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                tuid = block.get("tool_use_id", "")
                errors_by_id[tuid] = bool(block.get("is_error", False))
                content = block.get("content", "")
                if isinstance(content, list):
                    content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
                result_chars_by_id[tuid] = len(str(content))

    # Second pass: collect tool_use blocks and join with outcomes
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        for block in ev.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                tuid = block.get("id", "")
                input_preview = json.dumps(block.get("input", {}), default=str)[:200]
                calls.append({
                    "name": block.get("name", ""),
                    "input_preview": input_preview,
                    "is_error": errors_by_id.get(tuid, False),
                    "result_chars": result_chars_by_id.get(tuid, 0),
                })

    by_name: dict[str, int] = {}
    for c in calls:
        by_name[c["name"]] = by_name.get(c["name"], 0) + 1

    result_ev = next((e for e in events if e.get("type") == "result"), {})

    return {
        "total_calls": len(calls),
        "by_name": by_name,
        "calls": calls[:50],            # cap to avoid huge meta.json on chatty runs
        "calls_truncated": len(calls) > 50,
        "turns": result_ev.get("num_turns"),
        "stop_reason": result_ev.get("stop_reason"),
        "duration_ms": result_ev.get("duration_ms"),
    }
```

## File changes

| File                                                                                                                  | Type               | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                                |
| --------------------------------------------------------------------------------------------------------------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/orchestrator_runner.py`                                                                                      | Modify             | Branch `dispatch_subagent` on `DOCS_AGENT_DEBUG_DIR`. Add `_dispatch_streaming`, `_extract_final_assistant_text`, `_summarize_tool_use` helpers. Extend the existing CCE-9 `meta.json` write to include the `tool_use` block.                                                                                                                                                                                                          |
| `tests/orchestrator/test_dispatch_subagent_stream_json.py`                                                            | Create             | New test module. Monkeypatch `subprocess.run` to return a canonical stream-json NDJSON fixture. Assert: (1) returned `CompletedProcess.stdout` equals the concatenated text of the final assistant turn; (2) `<agent>.stream.jsonl` file written with raw bytes; (3) `<agent>.meta.json` contains the `tool_use` block with correct counts; (4) when `DOCS_AGENT_DEBUG_DIR` unset, the existing simple-print code path runs unchanged. |
| `tests/orchestrator/fixtures/cce12_stream_json/source_collector_with_tools.jsonl`                                     | Create             | Fixture: minimal but representative NDJSON capturing a system init, two `gh`-style tool_use turns with successful tool_results, and a final assistant text turn containing the canonical JSON.                                                                                                                                                                                                                                         |
| `tests/orchestrator/fixtures/cce12_stream_json/source_collector_no_tools.jsonl`                                       | Create             | Fixture: NDJSON for the empty-result case (no tool_use blocks, single assistant turn with `{"prs": [], "jira_issues": []}`).                                                                                                                                                                                                                                                                                                           |
| `docs/superpowers/measurements/2026-05-20-cce12-tool-use-baseline.md`                                                 | Create             | Re-run the CCE-10 5-run ceremony with diagnostics on. Per-run table: `tool_use.total_calls`, `tool_use.by_name`, `tool_use.stop_reason`, output prs count, output jira_issues count, root-cause category (A/B/C/D from the success criteria).                                                                                                                                                                                          |
| `docs/superpowers/measurements/2026-05-20-cce12-run[1-5]-*.{stream.jsonl,meta.json,stdout.txt,stderr.txt,prompt.txt}` | Create (generated) | Raw per-run artifacts from the 5-run ceremony, checked in for auditability.                                                                                                                                                                                                                                                                                                                                                            |
| `agents/source-collector.md`                                                                                          | **No change**      | Instrumentation must be orchestrator-side; perturbing the agent under measurement would invalidate the diagnostic.                                                                                                                                                                                                                                                                                                                     |

## Success criteria

1. With `DOCS_AGENT_DEBUG_DIR` set, every Mode B dispatch produces a `<agent>.stream.jsonl` and an extended `<agent>.meta.json` with a non-null `tool_use` block.
2. With `DOCS_AGENT_DEBUG_DIR` unset, `dispatch_subagent`'s subprocess call uses the existing simple `--print` form, identical to today.
3. All existing tests pass; new test module validates the stream-json path and the gate behavior.
4. 5 consecutive Mode B source-collector runs against the engineering-docs-agent repo produce categorized outcomes:
   - **A: Zero tool calls** → agent skipped the work (`total_calls == 0`)
   - **B: Tools called, data returned, agent discarded** → output `prs: []` despite non-empty `gh` tool_results
   - **C: Tools called, returned empty** → legitimate empty window
   - **D: Tools called, errored** → `is_error: true` on any tool_result
5. Measurement document published with the 5-run categorization breakdown. Document explicitly states which category dominates and what that implies for the follow-up fix ticket.

## Out of scope (deferred)

- Always-on stream-json as production default. This is a separable decision; we want diagnostics shipped first.
- Stream-json migration for other subagents as primary path. They get diagnostics when the gate is on, but their simple-print path remains canonical when off.
- Tool-use budgets / circuit breakers / retry-on-no-tool-calls. These need the diagnostic data to design well.
- Cost reporting via `total_cost_usd`. Captured raw in the stream but not surfaced in the summary; deferred until we have a use case.
- Schema versioning of `meta.json["tool_use"]`. The block is purely diagnostic; if the CLI's stream-json schema shifts we update the parser, no migration story needed.

## Risks and mitigations

| Risk                                                                         | Mitigation                                                                                                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Claude CLI stream-json schema shifts between versions                        | Parser is permissive — unknown event types skipped, only `system`/`assistant`/`user`/`result` inspected. Raw `.stream.jsonl` is always persisted so we can re-parse retroactively.                                                                                                                         |
| Final-text extraction misses content if the agent uses non-text final blocks | `_extract_final_assistant_text` concatenates ALL text blocks from the last assistant turn. Tested with multi-block fixture. If extraction returns empty, the subprocess "stdout" returned upstream is empty and the orchestrator's existing JSON-parse failure path triggers — same failure mode as today. |
| Stream-json adds latency to every diagnostic run                             | Acceptable. Diagnostics are gated and intended for measurement runs, not production. ~10–20% subprocess overhead is dwarfed by model latency.                                                                                                                                                              |
| Stream NDJSON could be huge for long sessions and inflate disk usage         | `calls[:50]` cap in summary keeps `meta.json` small. Raw `.stream.jsonl` is uncapped by design (forensics). Ops can prune old debug dirs manually; no automatic rotation in scope.                                                                                                                         |
| Test fixture drifts from real CLI output                                     | Fixtures are minimal and reference the documented stream-json schema. If the CLI changes shape, regenerate fixtures from a live run and update parser. The 5-run baseline measurement also validates against real output.                                                                                  |

## Open questions

None blocking. The architectural fork (stream-json over self-report) is resolved. Remaining choices (gate, scope, summary shape) made above as defensible defaults.

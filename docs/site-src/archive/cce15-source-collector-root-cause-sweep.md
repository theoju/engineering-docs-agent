---
description: "Two independent silent-failure modes in the source-collector dispatch\
  \ path and their fixes \u2014 phantom schema fields (closed by `additionalProperties:\
  \ false`) and explanatory-output-style hook injection (closed by `--setting-sources\
  \ project,local`)."
source_files:
- scripts/orchestrator_runner.py
- tests/orchestrator/test_dispatch_rescue.py
- tests/orchestrator/test_dispatch_subagent.py
- tests/orchestrator/test_dispatch_validated.py
- tests/schemas/test_source_collector_schema.py
last_reviewed: '2026-05-28'
status: draft
doc_kind: decision
sources: []
synthesized_into: []
---

# CCE-15: Source Collector Root Cause Sweep

CCE-15 diagnosed two independent failure modes in the source-collector dispatch path that caused the orchestrator to silently misread subagent output. Both modes were confirmed in CCE-14 production runs. This page documents the root causes, the fixes, and the test coverage that pins each behavior.

## Root causes

### Mode 1 — Phantom fields (schema gap)

The source-collector agent was emitting `{"prs": [], "jira_issues": [], "commits": []}` — a `commits` field that does not exist in the schema. Because the schema lacked `additionalProperties: false`, `validate_and_parse` accepted the output as schema-valid. The orchestrator treated it as a successful empty run and moved on, silently discarding any PRs the agent may have found.

### Mode 2 — Prose contamination (plugin injection)

The `explanatory-output-style` Claude plugin, when enabled in the user-level `settings.json`, fires a `SessionStart` hook that prepends prose like `★ Insight ─────────────────────────────────────` to every subprocess context. CCE-14 Run 4 confirmed this broke `json.loads()` on the raw stdout, causing `dispatch_subagent` to return `None` and the orchestrator to record `source_collector_invalid: returned None`.

## Fixes

### Schema tightening

`agents/schemas/source_collector.schema.json` gained `additionalProperties: false` at the top level and inside each PR item's object definition. Any phantom field — `commits`, `status`, `summary`, anything not in `properties` — now produces a `ValidationError` at the `validate_and_parse` layer. The orchestrator records `schema_invalid: source-collector: ...` in `partial_reasons` rather than silently accepting a broken run.

`tests/schemas/test_source_collector_schema.py:test_phantom_top_level_field_rejected` pins the Mode 1 regression with `test_phantom_top_level_field_rejected` and `test_phantom_per_pr_item_field_rejected`.

### `--setting-sources project,local`

`dispatch_subagent` in `scripts/orchestrator_runner.py:dispatch_subagent` now passes `--setting-sources project,local` to every `claude` subprocess. This tells the CLI to skip the user-level `settings.json` — the file where the `explanatory-output-style` plugin is registered. Project and local settings still load, but this repo has no `.claude/` directory so neither contributes plugin-enable state.

`--bare` was evaluated first but rejected: it disables OAuth/keychain authentication, breaking any host that relies on credential inheritance rather than `ANTHROPIC_API_KEY`. `--setting-sources project,local` closes the SessionStart-hook pathway while preserving authentication.

`tests/orchestrator/test_dispatch_subagent.py:test_dispatch_passes_setting_sources_flag` (`test_dispatch_passes_setting_sources_flag`) pins the flag, its value, and its position (must precede `-p`).

### `_rescue_json_object` — defense in depth

`scripts/orchestrator_runner.py` adds `_rescue_json_object(text)` as a fallback when `json.loads()` on the canonical text fails. The algorithm:

1. Find the first `{` in the text.
2. Scan forward, tracking brace depth while honoring JSON string state (open quote, escaped-quote skip).
3. When depth returns to zero, attempt `json.loads` on the slice.
4. Return the parsed dict on success, `None` otherwise.

The rescue is defense in depth: `--setting-sources` closes the known injection pathway, but other contamination patterns may exist (tool preambles, future plugin hooks). When the rescue succeeds, it records `prose_contamination_rescued: <agent-name>` in `out_reasons` so the event is visible in `state['current_run']['partial_reasons']` and in Slack/email notifications.

`tests/orchestrator/test_dispatch_rescue.py` covers: prose prefix with valid JSON, braces inside string literals, all-prose output (returns `None`), balanced-but-invalid pseudo-JSON (returns `None`), and multiple-object output (takes the first).

## `out_reasons` plumbing

`dispatch_subagent` accepts an optional `out_reasons: list[str] | None = None` parameter. When the rescue path fires, it appends `prose_contamination_rescued: <name>` to this list. `dispatch_validated` in `scripts/orchestrator_runner.py:dispatch_validated` passes its own collector down and merges the result into the reasons tuple it returns:

```python
dispatch_reasons: list[str] = []
raw = dispatch_subagent(
    name, inputs, dry_run_dir=dry_run_dir, cwd=cwd, out_reasons=dispatch_reasons
)
```

Callers at the orchestrator level iterate over the returned `reasons` list and call `add_partial(state, r)` for each entry. A sustained rescue rate becomes observable without any log scraping — it accumulates in `state.json` and surfaces in the run digest.

The parameter defaults to `None` for backward compatibility: all existing `dispatch_subagent` call sites that omit `out_reasons` continue to work unchanged. `tests/orchestrator/test_dispatch_rescue.py:test_dispatch_subagent_out_reasons_optional_backward_compatible` (`test_dispatch_subagent_out_reasons_optional_backward_compatible`) pins this contract.

## Test coverage map

| Test file                                           | What it pins                                                           |
| --------------------------------------------------- | ---------------------------------------------------------------------- |
| `tests/schemas/test_source_collector_schema.py`     | Schema tightening: phantom top-level and per-item fields rejected      |
| `tests/orchestrator/test_dispatch_subagent.py`  | `--setting-sources project,local` in argv, preceding `-p`              |
| `tests/orchestrator/test_dispatch_rescue.py`        | `_rescue_json_object` algorithm + `out_reasons` append                 |
| `tests/orchestrator/test_dispatch_validated.py` | Rescue reason flows through `dispatch_validated` into returned reasons |

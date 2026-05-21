# CCE-15: Source-Collector Root-Cause Sweep — Design Spec

**Jira:** [CCE-15](https://designitright.atlassian.net/browse/CCE-15)
**Date:** 2026-05-21
**Author:** Theo Jungeblut (with Claude Opus 4.7)
**Parent measurement:** [CCE-14 baseline doc](../measurements/2026-05-20-cce14-prompt-hardening-baseline.md)

## Problem

The CCE-14 prompt-hardening intervention (mandatory gated Procedure checklist + Forbidden outputs §5) reduced Category-A source-collector failures from 4/5 to 2/5 across the 5-run Mode B baseline, but missed acceptance criteria on both metrics by 1. The baseline doc identified two distinct residual failure modes and deferred them to this ticket.

During CCE-15 context exploration, both modes turned out to have cheaper root causes than the prompt-restructure escalation path the CCE-14 baseline doc proposed:

**Mode 1 — Checklist bypass (Runs 2, 3):** Agent emits `{"prs":[],"jira_issues":[],"commits":[]}` (note the phantom `commits` field) in a single ~4–5s turn with zero tool calls. The agent is hallucinating a non-canonical schema shape AND the orchestrator is silently accepting it as a "successful empty run" because `agents/schemas/source_collector.schema.json` does not set `additionalProperties: false` — it defaults to `true` in JSON Schema draft-07.

**Mode 2 — Prose contamination (Run 4):** Agent invoked `gh pr list` correctly, fetched real PR data, but the final assistant turn prepended an "★ Insight ─" prose block before the JSON. The "★ Insight" formatting is the exact signature of the `explanatory-output-style` plugin, which is installed in the parent session and propagates into the subprocess via its SessionStart hook. The hook injects `additionalContext` containing the explanatory-mode instructions into every new Claude process — including subagents dispatched via `claude -p`.

## Goals

Close both residual failure modes via root-cause fixes, not prompt escalation:

1. Eliminate the SessionStart-hook contamination pathway across all dispatched subagents.
2. Make phantom-field acceptances impossible at the schema layer.
3. Add a defense-in-depth rescue path for future prose contamination that might slip through other injection mechanisms.
4. Re-run the 5-run Mode B ceremony and meet a sharpened acceptance bar.

If acceptance is met, ship and close the residual-mode bucket. If acceptance still misses, file CCE-16 with the structural prompt change (XML output envelope or forced two-turn protocol) that this spec explicitly defers.

## Approach

**Approach selected: A — Root-cause sweep + defense in depth.**

Three composable fixes, each addressing a distinct root cause. Each is small (~5–20 lines) and the attribution is clean if the metric moves between runs.

Two alternatives were considered and rejected:

- **B — Root-cause only, no rescue.** Smallest diff but loses the partial_reasons signal for future regressions and has no fallback if `--bare` doesn't catch every contamination pattern.
- **C — Rescue only, no root-cause sweep.** Smallest blast radius but doesn't address Mode 1 (bypass) at all; masks rather than fixes the env-hygiene cause of Mode 2.

## Architecture

The intervention is three independent root-cause fixes layered across the existing pipeline, not a new component:

```
                    dispatch_subagent()
                          │
            ┌─────────────┼─────────────┐
            │             │             │
       Fix #1: argv   Fix #3: parse  (unchanged)
       (add --bare)   (rescue path)
                          │
                          ▼
                  json.loads(canonical_text)
                          │
                          ▼
                  dispatch_validated()
                          │
                          ▼
                   validate against
            agents/schemas/source_collector.schema.json
                          │
                  Fix #2: additionalProperties:false
                  rejects {prs, jira_issues, commits}
                          │
                          ▼
              partial_reasons accumulator
                  (existing CCE-5/10 path)
```

Files touched:

- `scripts/orchestrator_runner.py` — Fixes 1 + 3
- `agents/schemas/source_collector.schema.json` — Fix 2
- `tests/orchestrator/test_dispatch_subagent.py` — new `--bare` tests
- `tests/orchestrator/test_dispatch_rescue.py` (new file) — rescue helper tests
- `tests/orchestrator/test_dispatch_validated.py` — rescue propagation test
- `tests/schemas/test_source_collector_schema.py` — schema strictness tests
- `docs/superpowers/measurements/2026-05-21-cce15-root-cause-baseline.md` — re-measurement doc

## Components

### Fix #1: `--bare` flag in `dispatch_subagent`

Single argv addition, placed immediately after `claude` so it applies to the whole invocation. The `claude --help` documentation for `--bare`: "Minimal mode: skip hooks, LSP, plugin sync, attribution, auto-memory, background prefetches, keychain reads, and CLAUDE.md auto-discovery."

The existing `--plugin-dir <_PLUGIN_ROOT>` continues to pass the plugin set explicitly, so the source-collector agent (and all other agents) still loads correctly. Subagent role instructions come from `--agent <name>` + `--plugin-dir`; CLAUDE.md is for human authors and contributes no signal to a JSON-producing subagent.

```python
base_argv = [
    "claude",
    "--bare",
    "-p",
    prompt,
    "--agent", name,
    "--plugin-dir", str(_PLUGIN_ROOT),
    "--allowedTools", " ".join(_AGENT_ALLOWED_TOOLS),
]
```

`--bare` applies to ALL agents (not just source-collector). Rationale: consistent dispatch behavior across the pipeline; the same SessionStart-hook contamination class affects every subagent equally.

### Fix #2: `additionalProperties: false` in `source_collector.schema.json`

Two additions: top-level object and per-PR-item object. The `jira_issues` array has no per-item schema currently — tightening that is out of scope.

Before:

```json
{
  "type": "object",
  "required": ["prs", "jira_issues"],
  "properties": { ... }
}
```

After:

```json
{
  "type": "object",
  "required": ["prs", "jira_issues"],
  "additionalProperties": false,
  "properties": {
    "prs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["number", "url"],
        "additionalProperties": false,
        "properties": { ... }
      }
    },
    ...
  }
}
```

Effect: `{"prs":[],"jira_issues":[],"commits":[]}` → `schema_invalid: source_collector: additional properties not allowed: ['commits']` flows through the existing `dispatch_validated` path into `state['current_run']['partial_reasons']`. The phantom-field bypass becomes loud and auditable.

### Fix #3: Prose-tolerant JSON rescue in `dispatch_subagent`

New helper `_rescue_json_object(text: str) -> dict | None`. Algorithm:

1. Find the first `{` in `text`. If none, return `None`.
2. Walk forward, tracking brace depth. Honor JSON string state — track open `"`, skip escaped `\"`. Don't count braces inside string literals.
3. When depth returns to 0, attempt `json.loads(text[start:end+1])`.
4. On success, return the parsed dict. On `JSONDecodeError`, return `None`.
5. If the scan reaches end-of-string without depth returning to 0, return `None`.

Wiring in `dispatch_subagent`, replacing the existing strict-only parse:

```python
try:
    return json.loads(canonical_text), []
except json.JSONDecodeError:
    rescued = _rescue_json_object(canonical_text)
    if rescued is not None:
        return rescued, [f"prose_contamination_rescued: {name}"]
    return None, []
```

This changes `dispatch_subagent`'s return type from `dict | None` to `tuple[dict | None, list[str]]`. `dispatch_validated` already returns a tuple shape, so it merges dispatch-side rescue reasons into its own reasons list. Other callers updated in lockstep.

## Data flow

### Mode 2 (prose contamination) under the fix

1. Subprocess runs with `--bare` → no SessionStart hook fires → no "★ Insight" injection → agent emits clean JSON. **Mode 2 prevented at root.**
2. If a future contamination pattern slips through a different injection point, strict `json.loads` fails → `_rescue_json_object` extracts the JSON → returns `(dict, ["prose_contamination_rescued: source-collector"])` → orchestrator continues with rescued data and a visible audit trail.

### Mode 1 (checklist bypass) under the fix

1. Agent emits `{"prs":[],"jira_issues":[],"commits":[]}` as before. We do NOT prevent the bypass at the agent layer.
2. `dispatch_subagent` parses successfully → `dispatch_validated` runs schema check → `additionalProperties: false` rejects on `commits` → returns `(None, ["schema_invalid: source_collector: additional properties not allowed: ['commits']"])`.
3. Orchestrator's existing `partial_reasons` accumulator surfaces the bypass loud and clear. **Phantom-field acceptances become impossible.**

## Error handling

The intervention sits inside an existing error-handling spine and adds three precise behaviors without breaking anything else.

| Trigger                                                          | Before                 | After                                                                                                          |
| ---------------------------------------------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------- |
| Strict `json.loads(canonical_text)` succeeds                     | `return parsed_dict`   | `return (parsed_dict, [])`                                                                                     |
| Strict fails, rescue extracts a balanced object that round-trips | `return None`          | `return (rescued, ["prose_contamination_rescued: <name>"])`                                                    |
| Strict fails, no balanced object found                           | `return None`          | `return (None, [])`                                                                                            |
| Output has phantom field (e.g. `commits`)                        | passes schema silently | `(None, ["schema_invalid: source_collector: additional properties not allowed: ['commits']"])`                 |
| `--bare` invalidates an agent dependency we didn't anticipate    | n/a                    | dispatch returncode != 0 → existing generic-failure path; surfaces in stderr captured under `<run>.stderr.txt` |

Edge cases on the rescue path:

- **Multiple `{...}` objects in contaminated output:** take the FIRST balanced object. The agent's contract is "the canonical JSON is the response"; treating any later JSON as decorative matches the existing parse semantics.
- **Braces inside string literals** (e.g., `{"body": "see {detail}"}`): the brace-balanced scan honors string state.
- **Rescued object isn't schema-valid:** flows through `dispatch_validated`'s existing path, becomes `schema_invalid` plus the `prose_contamination_rescued` reason. Both are useful signal.
- **No `{` in the output at all:** returns `None`, same as today.

Every new path appends to `partial_reasons` with a unique prefix. No silent swallowing. This matches the project's existing convention (CCE-5 introduced `partial_reasons`; CCE-10 added `schema_invalid:` prefix; CCE-15 adds `prose_contamination_rescued:`).

## Testing

Three test layers + acceptance evidence.

### Unit tests (TDD: written before implementation)

| File                                                     | New tests                                                             | Asserts                                                                                           |
| -------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `tests/orchestrator/test_dispatch_subagent.py`           | `test_dispatch_passes_bare_flag`                                      | argv contains `"--bare"` as second element when `dry_run_dir is None`                             |
| `tests/orchestrator/test_dispatch_subagent.py`           | `test_dispatch_returns_tuple_on_strict_parse_success`                 | `(dict, [])` shape for clean JSON output                                                          |
| `tests/orchestrator/test_dispatch_subagent.py`           | `test_dispatch_returns_none_tuple_on_returncode_failure`              | `(None, [])` when subprocess exits nonzero                                                        |
| `tests/orchestrator/test_dispatch_rescue.py` (new)       | `test_rescue_extracts_first_balanced_object_from_prose_prefix`        | `"Insight: blah\n\n{...json...}"` → `(parsed, ["prose_contamination_rescued: source-collector"])` |
| `tests/orchestrator/test_dispatch_rescue.py` (new)       | `test_rescue_extracts_json_with_braces_in_string_literals`            | `{"body": "see {detail}"}` round-trips correctly through brace-balanced scan                      |
| `tests/orchestrator/test_dispatch_rescue.py` (new)       | `test_rescue_returns_none_when_no_opening_brace`                      | All-prose output → returns `(None, [])`                                                           |
| `tests/orchestrator/test_dispatch_rescue.py` (new)       | `test_rescue_returns_none_when_brace_extracted_object_does_not_parse` | Malformed JSON inside braces → returns `(None, [])`                                               |
| `tests/orchestrator/test_dispatch_rescue.py` (new)       | `test_rescue_takes_first_object_when_multiple_present`                | Multiple JSON objects in prose → first one wins                                                   |
| `tests/schemas/test_source_collector_schema.py` (extend) | `test_phantom_top_level_field_rejected`                               | `{"prs":[],"jira_issues":[],"commits":[]}` → `schema_invalid`                                     |
| `tests/schemas/test_source_collector_schema.py` (extend) | `test_phantom_per_pr_item_field_rejected`                             | `{"prs":[{"number":1,"url":"...","extra":"x"}], "jira_issues":[]}` → `schema_invalid`             |
| `tests/schemas/test_source_collector_schema.py` (extend) | `test_canonical_empty_shape_still_passes`                             | `{"prs":[],"jira_issues":[]}` still passes (regression guard)                                     |
| `tests/schemas/test_source_collector_schema.py` (extend) | `test_full_pr_with_all_known_fields_still_passes`                     | Real PR from CCE-14 Run 1 stdout still passes (regression guard)                                  |

### Integration test

`tests/orchestrator/test_dispatch_validated.py` — add one test asserting the `prose_contamination_rescued: <name>` reason propagates through `dispatch_validated` into the returned reasons list when rescue fires.

### Caller updates (lockstep with the tuple return change)

- `dispatch_validated` in `scripts/orchestrator_runner.py`: merge dispatch-side rescue reasons into its own reasons list.
- All existing tests unpacking `dispatch_subagent`'s return: update to expect tuple. Discovery command: `grep -rn "dispatch_subagent(" tests/`.

### Acceptance evidence

5-run Mode B ceremony against the IDENTICAL window `a2a9dba..b2cd07a` used by CCE-12 and CCE-14. Output: `docs/superpowers/measurements/2026-05-21-cce15-root-cause-baseline.md` with three-column side-by-side: CCE-12 → CCE-14 → CCE-15. Include all 5 runs' raw artifacts under `2026-05-21-cce15-run<N>-source-collector.{stream.jsonl,meta.json,stdout.txt,stderr.txt,prompt.txt}`.

### Acceptance criteria

| Metric                             | CCE-12  | CCE-14 | CCE-15 target                                                    |
| ---------------------------------- | ------- | ------ | ---------------------------------------------------------------- |
| Category A (empty + zero tools)    | 4 / 5   | 2 / 5  | **≤ 1 / 5**                                                      |
| `gh pr list` invocations           | 0 / 5   | 3 / 5  | **≥ 4 / 5**                                                      |
| Runs returning real PR data        | 0 / 5   | 1 / 5  | **≥ 3 / 5**                                                      |
| Prose contamination failures       | n/a     | 1 / 5  | **0 / 5**                                                        |
| Phantom-field acceptances (silent) | unknown | 2 / 5  | **0 / 5** (either prevented or visibly logged as schema_invalid) |

Acceptance is a clean PASS if all five rows hit target. Partial pass follows the CCE-14 precedent: ship as documented partial fix, file CCE-16 with specific residual scope.

## Out of scope

- Tightening the other 6 agent schemas (`gap_detector`, `pr_summarizer`, `page_author`, `content_validator`, `publish_verifier`, `notifier`) with `additionalProperties: false`. Same root cause applies, but expanding scope requires testing every agent's existing outputs against the tightened schemas. File-and-defer if appetite.
- Structural prompt changes to `agents/source-collector.md` (XML output envelope, forced two-turn protocol). Reserved for CCE-16 if root-cause fixes don't hit acceptance.
- Tightening the `jira_issues` array's per-item schema (no schema currently defined; would require designing the canonical jira-issue shape first).
- Changes to other subagents' invocation patterns beyond adding `--bare`.
- Schema changes to the source-collector's input contract.
- Changes to the orchestrator's `partial_reasons` surfacing UX in the writer/notifier stages.

## Risks

**`--bare` breaks an agent dependency we didn't anticipate.** Mitigation: 5-run dry-run pass against the test suite as Task 1 acceptance gate. If any test fails due to a now-missing capability, the failure is local and the fix path is clear (add the specific capability back via the explicit `--system-prompt`, `--mcp-config`, etc. flags that `--bare`'s docs enumerate).

**Schema tightening rejects an output shape we forgot to enumerate.** Mitigation: regression-test against the real PR object from CCE-14 Run 1's stdout, which is the most complex canonical output observed in production.

**Rescue path masks future agent prompt regressions.** Mitigation: every rescue invocation appends `prose_contamination_rescued: <name>` to `partial_reasons`. The writer agent already surfaces all `partial_reasons` to the user; a sustained rescue rate is visible at the pipeline summary layer. Operators see "this run had 1 prose_contamination_rescued" and can investigate.

**Acceptance criteria still miss (e.g., bypass rate drops to 1/5 but contamination escapes rescue once).** Per the CCE-14 precedent: ship the measurable improvement, document the residual, file CCE-16 with the structural prompt change scope. Don't escalate scope within this ticket.

## References

- [CCE-12](https://designitright.atlassian.net/browse/CCE-12) — stream-json diagnostic capture (the measurement infrastructure)
- [CCE-14](https://designitright.atlassian.net/browse/CCE-14) — prompt-hardening intervention (the partial fix this builds on)
- [CCE-14 baseline doc](../measurements/2026-05-20-cce14-prompt-hardening-baseline.md) — run-level evidence
- Per-run artifacts: `docs/superpowers/measurements/2026-05-20-cce14-run{1..5}-source-collector.{stream.jsonl,meta.json}`
- `claude --help` output for `--bare`: skip hooks, LSP, plugin sync, attribution, auto-memory, background prefetches, keychain reads, and CLAUDE.md auto-discovery
- `explanatory-output-style` plugin: `~/.claude/plugins/cache/claude-plugins-official/explanatory-output-style/1.0.0/hooks-handlers/session-start.sh`

---
description: Schema enforcement and validated dispatch for subagent output (CCE-4)
source_files:
- agents/*.md
- agents/schemas/*.schema.json
- scripts/orchestrator_runner.py
- scripts/verify_runner.py
- tests/agents/test_schema_md_sync.py
- tests/orchestrator/fakes_schema_invalid/*.json
- tests/orchestrator/test_dispatch_subagent.py
- tests/orchestrator/test_dispatch_validated.py
- tests/orchestrator/test_pipeline_integration.py
- tests/orchestrator/test_schema_invalid_soft_fail.py
- tests/orchestrator/test_verify_runner.py
last_reviewed: '2026-05-28'
status: draft
doc_kind: architecture
---

# Schema Enforcement (CCE-4)

Every subagent call is validated against a JSON schema before the orchestrator acts on its output. An invalid response records a specific reason in `partial_reasons` and lets the pipeline continue — it never crashes the run.

## Schema files

Each agent has a canonical JSON Schema file at `agents/schemas/<agent_name>.schema.json` (using underscores). The seven schemas are:

| Agent | Schema file |
|---|---|
| `source-collector` | `source_collector.schema.json` |
| `pr-summarizer` | `pr_summarizer.schema.json` |
| `page-author` | `page_author.schema.json` |
| `content-validator` | `content_validator.schema.json` |
| `gap-detector` | `gap_detector.schema.json` |
| `publish-verifier` | `publish_verifier.schema.json` |
| `notifier` | `notifier.schema.json` |

Each agent's `.md` file in `agents/` also carries an `## Output schema (canonical)` section whose JSON block must remain byte-for-byte equivalent to the `.schema.json` file. `tests/agents/test_schema_md_sync.py` enforces this: it reads the fenced block from the `.md` and compares it via `json.loads` to the `.json` file. A mismatch fails the test immediately, so you can't update one without updating the other.

## `validate_and_parse` — the type boundary

`scripts/contracts.py` is the central validation entry point.

```
validate_and_parse(name: str, raw: dict) → tuple[dataclass | None, list[str]]
```

It does three things in sequence:

1. Looks up `agents/schemas/<name>.schema.json`. Returns `(None, ["schema_missing: <name>"])` when the file doesn't exist — this catches new agents whose schema file wasn't committed yet.
2. Calls `jsonschema.validate(raw, schema)`. On failure, returns `(None, ["schema_invalid: <name>: <message>"])` where `<message>` is the `jsonschema.ValidationError.message` string.
3. Looks up the typed dataclass in `_DATACLASS_BY_NAME` (`scripts/contracts.py`) and constructs it from matching keys. Returns `(None, ["dataclass_missing: <name>"])` on an unknown agent name.

The dataclasses (`SourceCollectorResult`, `PrSummary`, `PageAuthorResult`, etc.) are frozen. Downstream code in the orchestrator uses them as a typed view on top of the raw dict — adding a field to a schema requires adding it to the corresponding dataclass and the `.schema.json` in the same change.

## `dispatch_validated` — the call site wrapper

`scripts/orchestrator_runner.py:_sha_in_window` composes `dispatch_subagent` with `validate_and_parse` and returns a two-tuple the orchestrator uses directly:

```
dispatch_validated(name, inputs, *, dry_run_dir, cwd) → (dict | None, list[str])
```

Return shapes:

| Outcome | dict | reasons |
|---|---|---|
| Schema-valid | raw dict | `[]` |
| Schema-valid + prose rescue (CCE-15) | raw dict | `["prose_contamination_rescued: <name>"]` |
| Schema-invalid | `None` | `["schema_invalid: <name>: ..."]` |
| Dispatch returned `None` | `None` | `[]` |
| Schema file missing | `None` | `["schema_missing: <name>"]` |

The orchestrator iterates `reasons` and calls `add_partial(state, r)` on each before checking whether the result is `None`. This means a schema failure produces a precise reason (`schema_invalid: source-collector: ...`) in `state.json`'s `current_run.partial_reasons`, not the generic `source_collector_invalid: returned None` that would follow if no specific reason were present.

`test_dispatch_validated.py` tests all four paths directly. `test_schema_invalid_soft_fail.py` covers the end-to-end case: it runs the full pipeline with a `fakes_schema_invalid/` fixture whose `fake_source_collector.json` intentionally fails the schema, then asserts exit code 0, exactly one `schema_invalid: source-collector: ...` reason, and no duplicate generic reason.

## Soft-fail contract

A schema-invalid subagent response **never blocks the pipeline**. The orchestrator always falls through to the fallback (`sources = {"prs": [], "jira_issues": []}` for `source-collector`, skipping the PR for `pr-summarizer`, etc.). `partial` is set to `true` and the specific `schema_invalid:` reason is visible in state and in the Slack/email digest.

This means a broken subagent (model regression, prompt drift, API change) degrades the nightly run to a partial rather than a hard failure. The specific reason in `partial_reasons` tells you which agent and which field violated the schema, so you can reproduce the failure from the debug artifacts and fix the schema or the agent prompt.

## Schema–MD sync rule

When you update a schema — adding a field, changing a type, tightening `additionalProperties` — you must update both:

1. `agents/schemas/<name>.schema.json` — the canonical file read at runtime.
2. The `## Output schema (canonical)` fenced block in `agents/<name>.md` — the in-file reference Claude reads when it acts as that agent.

`tests/agents/test_schema_md_sync.py:test_md_schema_block_matches_canonical_schema_file` runs this check for all seven agents on every `pytest` invocation. It uses `json.loads` on both sides so whitespace and key ordering don't matter, but the parsed structures must be equal. The test message tells you which file to update and which direction the mismatch is in.

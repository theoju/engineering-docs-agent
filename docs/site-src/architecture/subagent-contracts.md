---
description: 'Documents architecture subagent contracts: page-author''s JSON schema now accepts the failure-shape payload it emits when a page can''t be authored (null content/page_hint fields) instead of rejecting that payload as schema_invalid. The fix updates agents/schemas/page_author.schema.json and the canonical fenced schema block in agents/page-author.md in lockstep, adds a regression test (tests/agents/test_page_author_failure_payload.py) pinning the documented failure shape as valid, and regenerates the published contract doc.'
source_files:
  - agents/page-author.md
  - agents/schemas/page_author.schema.json
  - docs/site-src/api/contracts/page_author.schema.md
  - tests/agents/test_page_author_failure_payload.py
last_reviewed: '2026-09-26'
status: draft
---
# Subagent contracts

Every subagent's output shape exists in three places, and all three must agree:

1. **`agents/<name>.md`** — the canonical contract, written for the agent itself. Its `## Output schema (canonical)` section holds a fenced `json` block: the JSON Schema the agent's response must validate against.
2. **`agents/schemas/<name>.schema.json`** — the same schema as a standalone file. `validate_and_parse` (`scripts/contracts.py`) reads this file, not the `.md`, when it validates a dispatch's raw output.
3. **`scripts/contracts.py`** — a frozen dataclass per agent (`PageAuthorResult`, `GapVerdict`, and so on, keyed in `_DATACLASS_BY_NAME`). `validate_and_parse` constructs one from whichever schema-declared fields the raw dict carries.

`tests/agents/test_schema_md_sync.py` enforces that (1) and (2) are JSON-equivalent after `json.loads` on both sides — not byte-identical, so formatting can differ, but every key and type must match. There is no test enforcing that the dataclass in (3) matches the schema; nothing constructs one without going through `validate_and_parse` first, so a dataclass field the schema does not require is simply never populated. That makes the dataclass's own type hints **cosmetic at runtime** — `validate_and_parse` builds `kwargs` from `raw`, filtered only by `fields(cls)` name, with no independent type check — the schema is the actual gate. A fourth artifact, `docs/site-src/api/contracts/<name>.schema.md`, is generated from the schema file by `scripts/contracts_doc.py` and must never be hand-edited; regenerate it after any schema change.

Whenever you change an agent's output shape, edit the `.md` block and the `.schema.json` file in the same commit, then regenerate the contract doc. Editing only one drifts silently until the sync test catches it — or, worse, until a real dispatch does.

## A schema can reject its own documented failure shape (CCE-180)

A subagent's failure path is part of its contract, not an exception to it. `agents/page-author.md` documents exactly what the agent must return when it cannot author a page — `target_path` outside `agent_editable_paths`, for instance, returns `{"ok": false, "error": "path_not_agent_editable", "path": null}` — and that shape has to validate against the same schema as a successful `ok: true` response.

For most of this pipeline's history it didn't. `page_author.schema.json` typed `path`, `action`, and `diff_summary` as bare `"type": "string"`, so a documented `null` on any of them failed `jsonschema.validate` with a message of the shape `schema_invalid: page-author: None is not of type 'string'`. That message fired on 5 of 7 nightlies in one stretch (#267, #268, #270, #272, #275) — the dominant blocker on the degraded path, not an edge case.

The failure mode this produced is specific: `dispatch_validated` (`scripts/orchestrator_runner.py`) calls `validate_and_parse` before the fan-out loop ever inspects the payload, so a schema-invalid response returns `(None, reasons)` regardless of how sensible the agent's `ok: false` answer was. The loop's `out is None` branch then records `page_author_invalid: <rel>` (`degraded=True` — the page batch is folded into `deferred_pages_by_pr` and its PR is held out of the CCE-151 advance cursor, so the work is retried, not lost). The graceful branch that exists specifically to report a clean refusal — the `else` arm that formats `page_author_error: <rel>: <err>` from `out.get("error")` — was never reached, because `out` was `None` before it got there. The agent behaved exactly as its own contract instructed, and the contract's own schema rejected the result.

Note that `PageAuthorResult` (`scripts/contracts.py`) already declared `path: str | None = None`, `action: str | None = None`, and `diff_summary: str | None = None` — the dataclass had modeled this correctly all along. Only the JSON Schema, the layer `validate_and_parse` actually enforces, was stricter than the contract it was meant to encode.

The fix widens `path`, `action`, and `diff_summary` to `{"type": ["string", "null"]}` in both `agents/schemas/page_author.schema.json` and the fenced block in `agents/page-author.md`, kept in lockstep per `test_schema_md_sync.py`, with `docs/site-src/api/contracts/page_author.schema.md` regenerated from the schema file rather than hand-edited. `ok` stays the only required field, and only a **present** `null` is forgiven — an absent key, or a wrong non-null type (a `42` where a string or `null` belongs), still fails validation loudly. `tests/agents/test_page_author_failure_payload.py` pins both directions: the documented failure shape validates, and a genuine malformation still raises `jsonschema.ValidationError`.

This is the same shape as CCE-125's gap-detector fix, one layer over: there, `gap-detector`'s documented `needs_spec: null` "couldn't judge" outcome was a required `boolean` that the same `schema_invalid` path rejected, and the fix made present-null a first-class value there too (`agents/schemas/gap_detector.schema.json`, `agents/gap-detector.md`). The general lesson holds across both incidents: when an agent's contract documents a null-field failure shape, the schema — not the dataclass, not the prose — is what decides whether that shape is a valid answer or a malfunction, and it has to be tested against the exact payload the contract tells the agent to emit.

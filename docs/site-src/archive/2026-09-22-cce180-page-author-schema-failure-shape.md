---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/278
synthesized_into: []
doc_kind: decision
---

# CCE-180: page-author's schema rejected its own documented failure shape

## What broke

`schema_invalid: page-author: None is not of type 'string'` fired on 5 of the
last 7 nightlies (#267, #268, #270, #272, #275). It was the dominant blocker
on the degraded path.

The cause was a mismatch between what `agents/page-author.md` documents and
what `agents/schemas/page_author.schema.json` accepted. The agent's own
Failure handling section says: when `target_path` resolves outside
`agent_editable_paths`, return `{ok: false, error: "path_not_agent_editable",
path: <the target_path you were given>}`; when no path applies, "send
`null`". The schema, however, still typed `path`, `action`, and
`diff_summary` as plain `string`, so a page-author response that returned
`path: null` — exactly the failure shape the agent's own contract calls
for — failed schema validation instead of being treated as a normal,
handled failure.

Downstream, `dispatch_verified` returns `None` on a schema failure, and
validation runs before the graceful `page_author_error` branch ever gets a
chance to read the payload. The run recorded `page_author_invalid`, which
CCE-144 classifies as **degraded** — it holds the offending PR out of the
advance cursor rather than crashing the run, but it still meant the
orchestrator's oldest-first admission prefix couldn't document PRs that
page-author had, by design, declined to author.

## The fix

`agents/schemas/page_author.schema.json` now types `path`, `action`, and
`diff_summary` as `["string", "null"]` instead of bare `string`. The
canonical fenced schema block in `agents/page-author.md` was updated in the
same change, keeping the two in sync as `tests/agents/test_schema_md_sync.py`
requires for every agent schema. `docs/site-src/api/contracts/page_author.schema.md`
was regenerated from the updated schema via `scripts/contracts_doc.py` —
that file is auto-generated and was not hand-edited.

`tests/agents/test_page_author_failure_payload.py` pins the shape: a
present `null` on any of the three nullable fields now validates
(`test_present_null_is_accepted`), the exact documented failure payload
(`{"ok": false, "error": "path_not_agent_editable", "path": null}`) validates
(`test_documented_failure_payload_validates`), and a genuinely wrong
non-null type on those fields — the actual malfunction signal — still
fails schema validation (`test_wrong_non_null_type_still_fails`). A missing
`ok` key still fails too (`test_missing_ok_still_fails`).

## Why this is safe

The orchestrator's page-authoring loop reads only `ok` and `error` from a
page-author result — it uses its own `rel_posix` for the path it writes to,
never the agent's `path` field. Widening `path`/`action`/`diff_summary` to
accept `null` doesn't loosen anything the orchestrator actually depends on;
it just stops rejecting a payload the agent was already instructed to send.

This is the same pattern as CCE-125's gap-detector fix: a documented
null/unjudged outcome becomes a first-class, schema-valid value instead of
a validation failure, while an absent required key or a wrong non-null type
still fails loud. Present-null is forgiven; missing or malformed is not.

## Reference

CCE-180 (2026-09-22).

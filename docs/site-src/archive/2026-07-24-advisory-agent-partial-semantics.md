---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/193
synthesized_into: []
doc_kind: decision
---

# Advisory Agent Dispatch Failures Are Info-Only, Not Partial (2026-07-24)

## Context

`gap-detector` and `fact-checker` are the two advisory subagents in the eight-agent pipeline. Their output only ever feeds a note on the docs-agent PR — `fact-checker` populates `fact_check_warnings`, `gap-detector` populates the "Gaps flagged" section — and neither feeds the CCE-101 auto-merge gate. The blocking pipeline is the other five: source-collector, pr-summarizer, page-author, content-validator, notifier. That distinction is now a named convention in CLAUDE.md, but it was learned the hard way, twice.

**CCE-118** established the general mechanism: a subagent that returns valid JSON wrapped in prose — recovered by `_rescue_json_object` and schema-validated — was still recorded as a dispatch failure, flipping the whole run `partial` and blocking CCE-101 auto-merge on a purely cosmetic rescue. Six blocking-pipeline callsites (source-collector, pr-summarizer, page-author, content-validator, gap-detector, notifier) were moved onto `_record_dispatch_reasons(state, reasons, ok=<dispatch produced usable output>)`: a dispatch that returns usable output can only carry benign `prose_contamination_rescued` diagnostics, so those are `info_only`; genuine failures still flip `partial`.

**CCE-125** closed the last recurring `partial` driver visible on nightly PR #189. `gap-detector`'s own documented malformed-input fallback — `{"error":"malformed_input","needs_spec": null}` — failed its own schema, because `needs_spec` was typed as a required boolean. `validate_and_parse` returned `schema_invalid`, the callsite recorded `ok=False`, and the run flipped `partial` for an agent that had done exactly what its contract said to do when it couldn't judge the input. An advisory agent's honest "I don't know" was being punished as if it were a malfunction.

## Decision

Treat a documented "couldn't judge" outcome from an advisory agent as a first-class value in its schema, not as a schema-validation failure.

`agents/schemas/gap_detector.schema.json` now types `needs_spec` as `["boolean", "null"]` — still `required`, so the key must be present, but `null` is now a legal value rather than a type mismatch. A validated `needs_spec: null` verdict records an info-only `gap_detector_unjudged: pr_id=…` reason at the callsite and is **skipped**: it is never appended to the verdicts list, so it stays out of both "Gaps flagged" in the PR body and the CCE-89 digest. The run stays non-partial.

The downgrade is deliberately narrow. Only a **present** `null` is treated as unjudged-and-fine. An **absent** `needs_spec` key, a wrong non-null type, or unparseable output still fails schema validation and still flips `partial` — the genuine-agent-malfunction signal is preserved. Widening the downgrade to "anything that doesn't parse" would have hidden real gap-detector breakage behind the same info-only path that's meant for a documented, expected outcome.

## What changed

- **`agents/schemas/gap_detector.schema.json`** — `needs_spec` type widened from `boolean` to `["boolean", "null"]`, `required` unchanged. Edited in lockstep with the canonical fenced schema block in `agents/gap-detector.md`; `tests/agents/test_schema_md_sync.py` asserts `json.loads`-equality between the two so they cannot drift.
- **Published contract doc regenerated** — `docs/site-src/api/contracts/gap_detector.schema.md` was rebuilt via `python scripts/contracts_doc.py --repo-root . --config <host-config>`, never hand-edited.
- **Callsite handling** — the orchestrator callsite that consumes `dispatch_validated`'s gap-detector output checks for `needs_spec is None` and, when present, records `gap_detector_unjudged` as an info-only reason and skips appending the verdict, rather than treating a null as a downstream error.
- **CHANGELOG.md** — `[Unreleased] > Fixed` entry documents the CCE-125 fix, notes it as the last recurring partial driver from PR #189 (whose `citation_exists` driver CCE-124 had already fixed, and whose `prose_contamination_rescued: fact-checker` reason was already info-only since CCE-118), and records that gap-detector now joins fact-checker as an advisory agent whose "couldn't judge" is info-only.
- **CLAUDE.md** — a new Plugin Conventions bullet names both `gap-detector` and `fact-checker` as advisory agents whose dispatch failures never flip `partial`, cites the CCE-118/CCE-125 mechanism, and calls out the two reusable traps below.

This PR (#193) is docs-only: it changes only `CLAUDE.md` and `CHANGELOG.md`, not the schema or callsite code itself — those shipped under CCE-125. This page and the CLAUDE.md bullet capture the durable convention for future contributors extending the agent pipeline.

## Reusable traps

Two traps surfaced during CCE-125 that apply to any future schema or advisory-agent change:

1. **Schema and canonical doc block must move together.** When changing an agent's JSON schema, edit both `agents/schemas/<agent>.schema.json` and the canonical fenced block in `agents/<agent>.md` in the same change — `tests/agents/test_schema_md_sync.py` asserts they're `json.loads`-equal — then regenerate the published contract doc with `scripts/contracts_doc.py`. Never hand-edit `docs/site-src/api/contracts/*.schema.md` directly.
2. **`dispatch_validated` returns the raw dict, not the dataclass.** Consumers read gap-detector output with `.get()`; the dataclass type hint (`GapVerdict.needs_spec: bool | None`) is cosmetic at runtime. The JSON schema is the actual gate — a dataclass annotation change alone would not have fixed CCE-125.

## Out of scope

- Unifying `gap-detector` and `fact-checker` under one explicit `ADVISORY_AGENTS` set in code — a deferred refactor, still two separate callsites doing the same conceptual thing.
- Any change to the blocking pipeline's dispatch-failure semantics — source-collector, pr-summarizer, page-author, content-validator, and notifier still flip `partial` on any dispatch failure, benign-JSON-rescue exception aside (CCE-118).

## See also

- CCE-118: the general benign-JSON-rescue-is-info-only mechanism this decision extends.
- CCE-124: fixed the `citation_exists` partial driver on the same nightly PR #189 that CCE-125 closed out.
- `docs/superpowers/specs/2026-07-23-cce125-gap-detector-unjudged-advisory-design.md`: design spec.
- `agents/gap-detector.md`, `agents/schemas/gap_detector.schema.json`: the changed contract.
- `CLAUDE.md`, `CHANGELOG.md`: the source PR's actual diff.

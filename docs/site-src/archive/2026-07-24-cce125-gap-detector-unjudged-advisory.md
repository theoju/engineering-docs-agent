---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/192
synthesized_into: []
doc_kind: decision
---

# CCE-125: `gap-detector`'s `needs_spec: null` becomes a first-class "unjudged" value

**Ticket:** CCE-125 · **Date:** 2026-07-23 · **PR:** #192

## Problem

PR #189's nightly docs-agent run came out `partial`. Of its three `partial_reasons`, two were already handled — a `citation_exists` lint block (fixed by CCE-124) and a `prose_contamination_rescued` fact-checker note (already info-only since CCE-118). The third was the actual driver: `schema_invalid: gap-detector: None is not of type 'boolean'`.

The failure traced to a contradiction between `gap-detector`'s own documented behavior and its schema. `agents/gap-detector.md` instructs the agent, on malformed input, to return `{"error": "malformed_input", "needs_spec": null}` — but `agents/schemas/gap_detector.schema.json` declared `needs_spec` as a required `boolean`. `null` failed `jsonschema.validate` in `contracts.validate_and_parse`, which returned `(None, ["schema_invalid: ..."])`. At the callsite in `orchestrator_runner.py`, `_record_dispatch_reasons(state, reasons, ok=verdict is not None)` saw `ok=False` and flipped the run to `partial` — which blocks CCE-101 auto-merge.

`gap-detector` output is advisory: `needs_spec` only ever produces a "Gaps flagged" note in the What's New entry and PR body, and gap-notes are not part of the CCE-101 auto-merge gate (only `partial`, fact-checker warnings, and human commits gate merge). A single PR the agent couldn't judge shouldn't degrade the whole nightly run.

## Decision

`null` is now a valid value for `needs_spec`, meaning "the agent ran but could not judge this PR." A validated null verdict is recorded as an info-only `gap_detector_unjudged` reason and skipped — the run stays non-`partial`. This aligns the schema with the agent's already-documented `null` fallback instead of fighting it, and the check is deterministic regardless of what the LLM emits.

Alternatives considered and rejected: coercing the invalid null to a boolean (the schema still "lies" about what the agent can return); making `gap-detector` unconditionally info-only (loses the genuine-malfunction signal that CCE-118 deliberately preserved for this class of agent); defaulting to `true` on null (spurious gap-notes, dishonest); a prompt-only `null → false` rewrite (LLM-dependent, not durable, untestable); retry-then-rescue (spends the CCE-109 time budget for no real gain); and a general `ADVISORY_AGENTS` unification (correct direction, but broader than this bug — deferred as a follow-up).

## What changed

- **Schema.** `agents/schemas/gap_detector.schema.json` types `needs_spec` as `["boolean", "null"]`, still `required`. The canonical fenced schema block in `agents/gap-detector.md` carries the identical change — `tests/agents/test_schema_md_sync.py` asserts the two stay byte-for-byte equal via `json.loads`.
- **Prompt.** `agents/gap-detector.md`'s Failure handling section now documents `needs_spec: null` as the valid "couldn't judge" sentinel, and clarifies that only an absent key or a non-boolean, non-null value indicates genuine agent malfunction.
- **Dataclass.** `GapVerdict.needs_spec` in `scripts/contracts.py` is typed `bool | None`. This is cosmetic at runtime — `validate_and_parse` builds `GapVerdict` from `fields()`, but `dispatch_validated` itself returns the raw dict, not the dataclass, so orchestrator callers read `verdict.get("needs_spec")` and the schema is the real gate, not the type hint.
- **Callsite.** In `orchestrator_runner.py`, between the `verdict is None` handling and `gap_verdicts.append(verdict)`, a validated `needs_spec is None` verdict now records `add_partial(state, f"gap_detector_unjudged: pr_id={pr_id}", info_only=True)` and is skipped with `continue` — it's never appended to `gap_verdicts`, so it can't surface in the "Gaps flagged" section or the CCE-89 digest.

## Behavioral contract

| Agent output | Before | After |
| --- | --- | --- |
| `needs_spec: null` (present) — the documented malformed-input fallback | `schema_invalid` → partial | validates → info-only `gap_detector_unjudged`, no partial, no gap-note |
| `needs_spec` absent (key omitted) | `schema_invalid` → partial | `schema_invalid` (still `required`) → partial |
| `needs_spec` wrong non-null type (e.g. `"yes"`) | `schema_invalid` → partial | `schema_invalid` → partial |
| unparseable output / no JSON | dispatch returns `None` → partial | dispatch returns `None` → partial |

Only the present-`null` case is downgraded. An absent key, a wrong non-null type, or unparseable output still fails schema validation and still flips the run to `partial` — the genuine-agent-malfunction signal is preserved, not blanket-suppressed.

## Verification

- `tests/orchestrator/test_gap_detector_unjudged.py` covers the new callsite behavior: a null-verdict run stays non-`partial`, records `gap_detector_unjudged: pr_id=...` as info-only, and the verdict is excluded from "Gaps flagged".
- `tests/orchestrator/test_gap_detector_prid_injection.py::test_missing_needs_spec_still_flips_partial` uses an absent key (not `null`) and confirms the preserved-signal case stays green.
- `tests/contracts/test_contracts.py` covers `validate_and_parse` directly: `{"pr_id": "o/r#1", "needs_spec": null}` validates to `GapVerdict(needs_spec=None)` with no errors; an absent key or a wrong-typed value still returns `schema_invalid`.
- `tests/orchestrator/test_fact_checker.py` adds an additive regression lock confirming `prose_contamination_rescued` stays info-only — no fact-checker code changed; this only guards against the same partial-flip failure mode recurring on the fact-checker's advisory path.
- All ten `fake_gap_detector.json` dry-run fixtures carry `true`/`false`, not `null` — the nullable type is a strict superset, so none needed updating.

## Related

- `agents/gap-detector.md`, `agents/schemas/gap_detector.schema.json`
- `docs/superpowers/specs/2026-07-23-cce125-gap-detector-unjudged-advisory-design.md`
- CCE-118 (fact-checker dispatch failures are info-only) and CCE-120 (orchestrator-injected `pr_id`) establish the same advisory-agent posture this decision extends to `gap-detector`'s unjudged case.

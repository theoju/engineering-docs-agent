---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/193
synthesized_into: []
doc_kind: decision
---

# Decision: Advisory Agents Never Flip a Run to `partial` (2026-07-24)

## Context

Nightly PR #189 went `partial` for a single reason: `gap-detector`'s documented malformed-input fallback, `{"error": "malformed_input", "needs_spec": null}`, failed its own schema — `needs_spec` was declared a required non-nullable boolean, so `validate_and_parse` returned `schema_invalid`. The dispatch callsite recorded that as a failure via `_record_dispatch_reasons(ok=False)`, and the run flipped `partial`, blocking the CCE-101 auto-merge gate.

But `gap-detector`'s output only ever feeds an advisory "Gaps flagged" note in the PR body — it isn't part of the CCE-101 auto-merge gate at all. An agent that could not judge whether a page needs a spec has no bearing on whether the docs content itself is safe to merge. The same shape of bug had already been fixed once, for `fact-checker`, under CCE-118: a benign `prose_contamination_rescued` diagnostic from a schema-valid dispatch was flipping `partial` even though `fact-checker` output is advisory too.

CCE-125 fixed the immediate root cause (`gap_detector.schema.json` now types `needs_spec` as `["boolean", "null"]`, so a present `null` verdict validates and is treated as a first-class "unjudged" skip rather than a schema failure). PR #193 is the durable record of the general rule both fixes converge on: `gap-detector` and `fact-checker` are advisory agents, and an advisory agent's dispatch failure must never flip a run to `partial`.

## Decision

Only the blocking pipeline — `source-collector`, `pr-summarizer`, `page-author`, `content-validator`, `notifier` — can flip a nightly run to `partial`, via `_record_dispatch_reasons(state, reasons, ok=<dispatch produced usable output>)`. `gap-detector` and `fact-checker` are advisory: their output only feeds a PR-body note (`fact-checker` → `fact_check_warnings`; `gap-detector` → "Gaps flagged"), and gap-notes are not part of the CCE-101 auto-merge gate. A dispatch failure on either agent is recorded as an info-only reason and the run stays non-`partial`.

CCE-125's specific mechanism for `gap-detector`:

- `agents/schemas/gap_detector.schema.json` types `needs_spec` as `["boolean", "null"]` — still `required`, so the key must be present, but `null` is now a valid value rather than a schema violation.
- A validated verdict with `needs_spec: null` records an info-only `gap_detector_unjudged` reason at the callsite and is **skipped** — it is never appended to the gaps list, so it stays out of both the "Gaps flagged" PR-body section and the CCE-89 digest.
- Only a **present** `null` is downgraded this way. An **absent** `needs_spec` key, a wrong non-null type, or unparseable output still fails schema validation and still flips `partial` — the genuine-agent-malfunction signal is preserved. The distinction is "the agent looked and couldn't tell" versus "the agent's output can't be trusted at all."

This mirrors the CCE-118 fix for `fact-checker`, where a schema-valid dispatch carrying only a benign `prose_contamination_rescued` diagnostic is `info_only` because a genuine schema failure would already force `out=None` at that callsite.

## Two reusable traps

Landing CCE-125 surfaced two traps worth keeping in mind for any future agent-schema change:

1. **Schema and canonical markdown block must move together.** When you change an agent's JSON schema, edit both `agents/schemas/<agent>.schema.json` and the canonical fenced block in `agents/<agent>.md` in lockstep — `tests/agents/test_schema_md_sync.py` asserts `json.loads`-equality between the two. After that, regenerate the published contract doc with `python scripts/contracts_doc.py --repo-root . --config <host-config>`; never hand-edit `docs/site-src/api/contracts/*.schema.md` directly.
2. **`dispatch_validated` returns a raw dict, not a typed dataclass.** Consumers read the verdict with `.get()`, so the dataclass type hint (`GapVerdict.needs_spec: bool | None`) is cosmetic at runtime — the JSON Schema is the real gate. A type annotation on the dataclass does not enforce anything the schema doesn't already enforce.

## Out of scope

- A general `ADVISORY_AGENTS` set unifying the handling for `gap-detector` and `fact-checker` at a single point — deferred as a follow-up refactor. Today the two agents are handled by parallel, agent-specific logic rather than one shared abstraction.

## See also

- CCE-118: the earlier fix that made a benign `fact-checker` JSON rescue info-only, establishing the same principle for that agent.
- CCE-127: a related but distinct failure mode — a failed GitHub App-token step degrading a run to `partial` through the existing `_maybe_auto_merge` interlock, not through an advisory agent.
- `docs/superpowers/specs/2026-07-23-cce125-gap-detector-unjudged-advisory-design.md`: design spec for the CCE-125 mechanism.
- `agents/schemas/gap_detector.schema.json`, `agents/gap-detector.md`: the schema and canonical contract this decision keeps in sync.
- `CHANGELOG.md`: CCE-125 entry under `[Unreleased] / Fixed`.

---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/192
synthesized_into: []
doc_kind: decision
---

# CCE-125: gap-detector `needs_spec: null` Becomes a First-Class "Unjudged" Value (2026-07-23)

## Context

Nightly PR #189 came out `partial` for three reasons. Two were already understood: `citation_exists` lint_block was fixed by CCE-124, and `prose_contamination_rescued: fact-checker` had already been info-only since CCE-118. The third was the sole remaining driver: `schema_invalid: gap-detector: None is not of type 'boolean'`.

The root cause was a contract mismatch. `agents/gap-detector.md` instructs the agent, on malformed input, to return `{"error": "malformed_input", "needs_spec": null}` — but `agents/schemas/gap_detector.schema.json` declared `needs_spec` as a required `boolean`. `null` fails that validation: `contracts.validate_and_parse` (`scripts/contracts.py`) calls `jsonschema.validate`, which raises, and the function returns `(None, ["schema_invalid: ..."])`. At the callsite in `scripts/orchestrator_runner.py`, `_record_dispatch_reasons(state, reasons, ok=verdict is not None)` sees `ok=False` and calls `add_partial(info_only=False)` — flipping the whole run to `partial`, which blocks the CCE-101 auto-merge gate.

`gap-detector` is downstream of the blocking pipeline. Its `needs_spec` verdict only ever produces a "Gaps flagged" note in the What's New entry and PR body — it is not part of the CCE-101 merge gate (only `partial`, fact-checker warnings, and human commits gate merge). An agent that ran and honestly said "I can't judge this one PR" degrading an entire nightly run was the bug, not the agent's behavior.

## Decision

Make `null` a first-class, schema-valid value for `needs_spec`, meaning "the agent ran but could not judge this PR." A validated `null` verdict is recorded as an **info-only** `gap_detector_unjudged` reason and skipped from further processing; the run stays non-partial. This aligns the schema with the agent's already-documented fallback instead of fighting it, and the outcome is deterministic regardless of what the LLM emits.

Alternatives considered and rejected:

| Alternative | Why rejected |
| --- | --- |
| Coerce the invalid `null` at the callsite | Worse-factored; the schema still "lies" about what the agent legitimately returns. |
| Broad "gap-detector unconditionally info-only" | Loses the genuine-breakage signal and reverses CCE-118's deliberate placement of the ok/info-only split. |
| Default `needs_spec` to `true` on `null` | Produces spurious gap notes — dishonest about what the agent actually judged. |
| Prompt-only fix (`null` → `false`) | LLM-dependent, not deterministically durable, untestable. |
| Retry-then-rescue | YAGNI; spends the CCE-109 time budget for no durable gain. |
| General `ADVISORY_AGENTS` policy unification | Correct direction but broadens scope beyond this bug — deferred as a follow-up. |

Only a *present*, schema-valid `null` is downgraded. Genuine structural failures — an absent `needs_spec` key, a wrong non-null type, or unparseable output — still fail `validate_and_parse` before reaching the new branch, so `dispatch_validated` still returns `None` and the run still flips `partial`. The malfunction signal is preserved everywhere except the one case that was never actually a malfunction.

## What changed

- **Schema** (`agents/schemas/gap_detector.schema.json`) — `needs_spec` is now typed `["boolean", "null"]`, still listed in `required`.
- **Canonical schema block** (`agents/gap-detector.md`) — the same change, kept in lockstep with the JSON schema; `tests/agents/test_schema_md_sync.py` asserts `json.loads`-equality between the two.
- **Dataclass** (`scripts/contracts.py`) — `GapVerdict.needs_spec` is typed `bool | None`. This is cosmetic at runtime: frozen dataclasses don't enforce annotations, and `dispatch_validated` returns the raw dict, not the dataclass, so the schema — not the dataclass — is the real gate.
- **Callsite** (`scripts/orchestrator_runner.py`) — between the dispatch's `_record_dispatch_reasons` call and the existing `gap_verdicts.append(verdict)`, a new branch:

  ```python
  if verdict.get("needs_spec") is None:
      add_partial(state, f"gap_detector_unjudged: pr_id={pr_id}", info_only=True)
      continue
  gap_verdicts.append(verdict)
  ```

  This is emitted directly with `info_only=True`, not routed through `_record_dispatch_reasons` (which is scoped to dispatch-level reasons). The `null` verdict is never appended to `gap_verdicts`, so it stays out of both the "Gaps flagged" What's New block and the CCE-89 PR digest. The partial-flip fix itself comes from the schema change — the verdict now validates, so `verdict is not None` and `ok=True` upstream — this branch supplies the observability that the dropped `error` field would otherwise cost.
- **Prompt** (`agents/gap-detector.md`) — documents `needs_spec: null` as the valid "couldn't judge" sentinel, and states explicitly that only an absent field or a non-boolean, non-null value counts as genuine malfunction.
- **Generated doc** (`docs/site-src/api/contracts/gap_detector.schema.md`) — regenerated via `scripts/contracts_doc.py` so the `needs_spec` row reads `boolean | null`. This doc is auto-generated and is not hand-edited.
- **Fact-checker regression lock.** A fact-checker-specific test asserts `prose_contamination_rescued` stays info-only, pointed at the fact-checker advisory path rather than the shared `_record_dispatch_reasons` helper (which already had its own coverage). No fact-checker code changed — the test exists to keep the CCE-118 behavior from regressing alongside this change.

## Error handling / degradation

| gap-detector output | Before CCE-125 | After CCE-125 |
| --- | --- | --- |
| `needs_spec: null` (present) — the documented malformed-input fallback | `schema_invalid` → **partial** | Validates → info-only `gap_detector_unjudged`, verdict skipped, no partial, no gap-note |
| `needs_spec` absent (key omitted) | `schema_invalid` → partial | `schema_invalid` (still `required`) → **partial** |
| `needs_spec` wrong non-null type (e.g. `"yes"`) | `schema_invalid` → partial | `schema_invalid` → **partial** |
| Unparseable / no JSON | dispatch returns `None` → partial | dispatch returns `None` → **partial** |

## Testing

- **Contracts** — `{"pr_id": "o/r#1", "needs_spec": null}` validates to `GapVerdict(needs_spec=None)` with no errors; `needs_spec` absent produces `schema_invalid`; wrong type (`"yes"`) produces `schema_invalid`.
- **Orchestrator** (`tests/orchestrator/test_gap_detector_unjudged.py`) — a `null`-verdict run stays `partial is False`, records `gap_detector_unjudged: pr_id=...` as info-only, and the verdict is excluded from "Gaps flagged". A `needs_spec`-absent verdict still flips `partial is True`.
- **Schema/doc sync** — `tests/agents/test_schema_md_sync.py` stays green after the schema and canonical-block edits.
- **Fact-checker regression** (`tests/orchestrator/test_fact_checker.py`) — `prose_contamination_rescued` stays info-only, locking in the CCE-118 behavior.

Blast radius was checked in two adversarial passes: no code constructs `GapVerdict(...)` directly (only `test_contracts.py` reads `.pr_id`); both `needs_spec` readers use `.get()` truthiness, so `None` is naturally excluded; all existing `fake_gap_detector.json` fixtures carry `true`/`false`, and nullable is a superset so they stay valid; `test_gap_detector_prid_injection.py::test_missing_needs_spec_still_flips_partial` uses an absent key (not `null`), so it stays green and exercises exactly the preserved-signal case; no JS/mjs/workflow consumer reads the gap-detector schema.

## Out of scope

- The general `ADVISORY_AGENTS` unification (one explicit set covering both gap-detector and fact-checker) — deferred as a follow-up.
- Any change to fact-checker's own dispatch or schema — the fact-checker test added here is a regression lock only, not a behavior change.

## See also

- CCE-118: the original blocking-vs-advisory dispatch reason split (`_record_dispatch_reasons`) that this decision extends.
- CCE-101: the auto-merge gate that a `partial` run blocks — the reason this class of failure matters.
- `docs/superpowers/specs/2026-07-23-cce125-gap-detector-unjudged-advisory-design.md`: design spec.
- `docs/superpowers/plans/2026-07-23-cce125-gap-detector-unjudged-advisory.md`: implementation plan.
- `agents/gap-detector.md`, `agents/schemas/gap_detector.schema.json`, `scripts/orchestrator_runner.py`, `scripts/contracts.py`: the changed surfaces.

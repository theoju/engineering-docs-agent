---
ticket: CCE-125
status: approved
date: 2026-07-23
supersedes_partial_driver: PR #189 (schema_invalid: gap-detector)
---

# CCE-125 — gap-detector `needs_spec: null` becomes a first-class "unjudged" value

## Problem

PR #189's nightly docs-agent run came out **partial**. Its actual `partial_reasons`:

- `lint_block: … citation_exists …` — fixed by **CCE-124** (merged, `main@4ac93ba`).
- `prose_contamination_rescued: fact-checker` — already **info-only** since **CCE-118**; never flipped partial (present for transparency only).
- `schema_invalid: gap-detector: None is not of type 'boolean'` — **the sole remaining partial driver.**

## Root cause

`agents/gap-detector.md:74` instructs the agent, on malformed input, to return
`{"error": "malformed_input", "needs_spec": null}`. But `agents/schemas/gap_detector.schema.json`
declares `needs_spec` as a **required boolean**. `null` fails validation:

`contracts.validate_and_parse` (`scripts/contracts.py:103`) → `jsonschema.validate` raises →
returns `(None, ["schema_invalid: gap-detector: None is not of type 'boolean'"])`. At the callsite
(`scripts/orchestrator_runner.py:1899-1903`), `_record_dispatch_reasons(state, reasons, ok=verdict is not None)`
sees `ok=False` → `add_partial(info_only=False)` → **flips the run to partial**, which blocks CCE-101 auto-merge.

gap-detector output is **advisory**: `needs_spec` only produces a "Gaps flagged" note in the What's New
entry / PR body (`orchestrator_runner.py:1915`, `:2069`), which is **not** in the CCE-101 auto-merge gate
(only `partial`, fact-checker warnings, and human commits gate merge). A "couldn't judge one PR" degrading
the whole run is the bug.

## Decision (Rank 1 — `null` as first-class "unjudged")

Make `null` a _valid_ value for `needs_spec`, meaning "the agent ran but could not judge this PR." A
validated null verdict is recorded as an **info-only** `gap_detector_unjudged` reason and skipped; the run
stays non-partial. This aligns the schema with the agent's already-documented `null` fallback rather than
fighting it, and it is deterministic — it holds regardless of what the LLM emits.

Alternatives considered and rejected (see grill session): coerce-the-invalid-null (worse-factored, schema
still "lies"); broad "gap-detector unconditionally info-only" (loses the genuine-breakage signal, reverses
CCE-118's deliberate placement); conservative default-`true` (spurious notes, dishonest); prompt-only
`null→false` (LLM-dependent, not deterministically durable, untestable); retry-then-rescue (YAGNI, spends
the CCE-109 budget); general `ADVISORY_AGENTS` policy (correct architecture but broadens scope beyond this
bug — deferred as a possible follow-up).

## Behavioral contract change (intended, explicit)

| Agent output                                                | Before                         | After                                                                      |
| ----------------------------------------------------------- | ------------------------------ | -------------------------------------------------------------------------- |
| `needs_spec: null` (present) — the malformed-input fallback | `schema_invalid` → **partial** | validates → **info-only `gap_detector_unjudged`**, no partial, no gap-note |
| `needs_spec` **absent** (key omitted)                       | `schema_invalid` → partial     | `schema_invalid` (still `required`) → **partial**                          |
| `needs_spec` wrong non-null type (e.g. `"yes"`)             | `schema_invalid` → partial     | `schema_invalid` → **partial**                                             |
| unparseable / no JSON                                       | dispatch None → partial        | dispatch None → **partial**                                                |

This is a real shift: the agent's _malformed-input_ case (which emits present-`null`) now downgrades from
partial to advisory. That is the intended fulfillment of "couldn't judge is advisory." The genuine-malfunction
signal (absent key / wrong type / unparseable — the agent's output is structurally broken, not merely
undecided) is **preserved**.

## Design

### Touch-points

1. **Schema** `agents/schemas/gap_detector.schema.json:8` — `needs_spec` → `{"type": ["boolean", "null"]}`, keep in `required`.
2. **Canonical schema block** `agents/gap-detector.md:35` — same change, **in lockstep** (guarded by `tests/agents/test_schema_md_sync.py`, which asserts `json.loads`-equality of the fenced block and the `.json` file).
3. **Dataclass** `scripts/contracts.py:54` — `needs_spec: bool` → `needs_spec: bool | None` (cosmetic at runtime — frozen dataclasses don't enforce annotations, and `dispatch_validated` returns the raw dict, not the dataclass; kept for honesty and static typing, style matches existing `str | None`).
4. **Callsite** `scripts/orchestrator_runner.py` — insert **between** `:1903`'s `continue` and `:1904`'s `gap_verdicts.append(verdict)`:

   ```python
   if verdict.get("needs_spec") is None:
       add_partial(state, f"gap_detector_unjudged: pr_id={pr_id}", info_only=True)
       continue
   ```

   Emitted **directly** with `info_only=True` (not routed through `_record_dispatch_reasons`, which is for
   dispatch reasons). The null verdict is **not** appended to `gap_verdicts`, so it never leaks into "Gaps
   flagged" (`:1915`) or the CCE-89 digest (`:2069`). The partial-flip fix itself comes from touch-point 1
   (the verdict now validates → `verdict is not None` → `ok=True` → any residual reasons are already
   info-only); this branch supplies the _observability_ the dropped `error` field would otherwise cost us.

5. **Prompt** `agents/gap-detector.md:74` — document `needs_spec: null` as the valid "couldn't judge" sentinel.
6. **Generated doc** `docs/site-src/api/contracts/gap_detector.schema.md` — regenerate via `scripts/contracts_doc.py` so the `needs_spec` row reads `boolean | null` (avoids a stale/phantom diff; no test enforces it, but the repo's regenerate-don't-hand-edit convention does).

### Fact-checker (separate, additive)

Add a **fact-checker-specific** regression lock-test asserting `prose_contamination_rescued` stays info-only
(does not flip partial). Point it at the fact-checker advisory path, **not** the shared
`_record_dispatch_reasons` helper (already covered by `tests/orchestrator/test_record_dispatch_reasons.py`
and `tests/orchestrator/test_benign_rescue_not_partial.py`). No fact-checker code change.

## Testing (TDD)

1. **contracts** — `{"pr_id": "o/r#1", "needs_spec": null}` validates → `GapVerdict(needs_spec=None)`, `errors == []`.
2. **contracts** — `needs_spec` absent → `(None, ["schema_invalid: … needs_spec …"])`; wrong type (`"yes"`) → `(None, [...])`.
3. **orchestrator** — a null-verdict run stays `partial is False`, records `gap_detector_unjudged: pr_id=…` (info-only), and the verdict is excluded from "Gaps flagged".
4. **orchestrator** — a `needs_spec`-absent verdict **still** flips `partial is True` (signal preserved).
5. **schema-md sync** — stays green after touch-points 1+2.
6. **fact-checker** — `prose_contamination_rescued` stays info-only (additive lock-test).

## Blast radius (verified by two adversarial red-team passes)

- No `GapVerdict(...)` construction sites; only reader `test_contracts.py:64` reads `.pr_id`.
- Both `needs_spec` readers (`:1915`, `:2069`) use `.get()` truthiness → `None` naturally excluded.
- All 10 `fakes*/fake_gap_detector.json` fixtures carry `true`/`false` → nullable is a superset → stay valid.
- `test_gap_detector_prid_injection.py::test_missing_needs_spec_still_flips_partial` uses an **absent** key (not null) → stays green (and is exactly the preserved-signal case).
- No JS/mjs/workflow consumer of the gap-detector schema.

## Validation

TDD (red → green per task); post-implementation adversarial workflow (correctness / test-non-vacuity /
blast-radius) mirroring CCE-124; ships via `/ship` with `CCE-125` in the PR title (jira-transition source of truth).

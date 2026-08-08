---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/192
synthesized_into: []
doc_kind: decision
---

# CCE-125: gap-detector `needs_spec: null` becomes a first-class "unjudged" value

PR #189's nightly run came out `partial` for three reasons. Two were already fixed
(`citation_exists` severity by CCE-124; `prose_contamination_rescued` was already
info-only since CCE-118). The third was new: `schema_invalid: gap-detector: None is
not of type 'boolean'`. That one was the last recurring driver, and it was a false
alarm — the agent hadn't malfunctioned, it had done exactly what its own prompt told
it to do.

## The bug

`gap-detector`'s documented malformed-input fallback is `{"error": "malformed_input",
"needs_spec": null}` (`agents/gap-detector.md`). But `agents/schemas/gap_detector.schema.json`
declared `needs_spec` as a required `boolean`. `null` fails that check every time.

In `scripts/contracts.py`, `validate_and_parse` runs `jsonschema.validate`, catches the
failure, and returns `(None, ["schema_invalid: ..."])`. At the callsite in
`scripts/orchestrator_runner.py`, `_record_dispatch_reasons(state, reasons, ok=verdict
is not None)` saw `ok=False` and called `add_partial` with `info_only=False` — flipping
the whole nightly run to `partial`, which blocks CCE-101 auto-merge.

That's disproportionate. `gap-detector` is advisory: its `needs_spec` verdict only
produces a "Gaps flagged" note in the What's New entry and PR body — it was never part
of the CCE-101 auto-merge gate (only `partial`, fact-checker warnings, and human commits
are). One PR the agent couldn't judge shouldn't degrade the entire run.

## Decision

Treat `null` as a valid, first-class "unjudged" value instead of fighting the agent's
own documented fallback.

- `gap_detector.schema.json` now types `needs_spec` as `["boolean", "null"]`, still
  `required`. The canonical fenced schema block in `agents/gap-detector.md` was updated
  in lockstep (the two are asserted equal by `tests/agents/test_schema_md_sync.py`).
- At the callsite, once a verdict validates, `orchestrator_runner.py` checks
  `verdict.get("needs_spec") is None`. If so, it records an **info-only**
  `gap_detector_unjudged: pr_id=<id>` reason via `add_partial(..., info_only=True)` and
  `continue`s — the verdict is never appended to `gap_verdicts`, so it's excluded from
  both the "Gaps flagged" What's New section and the CCE-89 digest.
- `scripts/contracts.py`'s `GapVerdict.needs_spec` annotation moved to `bool | None` for
  honesty (this is cosmetic at runtime — `dispatch_validated` returns the raw dict, not
  the dataclass, so nothing actually enforces it; the schema is the real gate).

What stays unchanged, deliberately: an **absent** `needs_spec` key, a wrong non-null
type (e.g. `"yes"`), or unparseable agent output all still fail schema validation and
still flip the run to `partial`. Those are genuine structural failures — the agent's
output is broken, not merely undecided — and that signal is preserved.

| Agent output | Before | After |
| --- | --- | --- |
| `needs_spec: null` (present) | `schema_invalid` → partial | validates → info-only `gap_detector_unjudged`, no partial, no gap-note |
| `needs_spec` absent | `schema_invalid` → partial | `schema_invalid` → partial (unchanged) |
| `needs_spec` wrong non-null type | `schema_invalid` → partial | `schema_invalid` → partial (unchanged) |
| unparseable / no JSON | dispatch `None` → partial | dispatch `None` → partial (unchanged) |

## Alternatives considered

- **Coerce the invalid null elsewhere** — worse-factored; the schema would still "lie"
  about what the agent is allowed to emit.
- **Make gap-detector unconditionally info-only** — loses the genuine-malfunction
  signal and reverses CCE-118's deliberate placement of that boundary.
- **Default to `true` on null** — spurious "Gaps flagged" notes; dishonest about what
  the agent actually judged.
- **Prompt-only `null` → `false` rewrite** — LLM-dependent, not deterministically
  durable, and not testable.
- **Retry-then-rescue** — YAGNI, and spends the CCE-109 time budget on a case that
  doesn't need it.
- **A general `ADVISORY_AGENTS` policy unifying gap-detector and fact-checker** —
  correct direction architecturally, but broader than this bug. Deferred as a possible
  follow-up.

## Why this matters beyond CCE-125

This is the same shape as CCE-118 (`fact-checker`) and CCE-127 (App-token failures): an
agent's own documented "I couldn't judge this" fallback must not read as a malfunction.
Both `gap-detector` and `fact-checker` are advisory agents — their dispatch failures are
info-only and never flip `partial` on their own — but only the specific value the agent
was told to emit for "couldn't judge" (`null`, present) gets that treatment. Anything
that looks like the agent itself broke — a missing required field, a wrong type, output
that doesn't parse as JSON at all — still flips `partial`, because that distinction is
the entire point: advisory-uncertain and broken are different failure modes and the run
needs to be able to tell them apart.

Two mechanical traps worth carrying forward whenever an agent's JSON schema changes:

1. Edit both `agents/schemas/<agent>.schema.json` and the canonical fenced block in
   `agents/<agent>.md` in the same change — `tests/agents/test_schema_md_sync.py`
   enforces `json.loads`-equality between them — then regenerate the published contract
   doc with `scripts/contracts_doc.py` rather than hand-editing
   `docs/site-src/api/contracts/*.schema.md`.
2. `dispatch_validated` returns the raw dict, not the dataclass. Consumers use
   `.get()`, so a dataclass type-hint change like `GapVerdict.needs_spec: bool | None`
   is cosmetic — the schema is the real gate at runtime.

Full design record: `docs/superpowers/specs/2026-07-23-cce125-gap-detector-unjudged-advisory-design.md`.

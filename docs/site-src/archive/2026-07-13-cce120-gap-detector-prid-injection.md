---
description: "The orchestrator now injects its own authoritative `pr_id` into\
  \ the gap-detector verdict before schema validation, instead of requiring the\
  \ LLM subagent to echo an identity value the orchestrator already constructs."
source_files:
- scripts/orchestrator_runner.py
- tests/orchestrator/test_dispatch_validated_inject.py
- tests/orchestrator/test_gap_detector_prid_injection.py
last_reviewed: '2026-07-14'
status: draft
doc_kind: decision
sources:
- https://github.com/theoju/engineering-docs-agent/pull/175
synthesized_into: []
---

# CCE-120: Orchestrator-Injected `pr_id` for Gap-Detector Verdicts

## Problem

`agents/schemas/gap_detector.schema.json` marks `pr_id` as required. Nightly PR #173 (2026-07-12) went `partial` for exactly one reason: `schema_invalid: gap-detector: 'pr_id' is a required property`. That single reason was enough to block CCE-101 auto-merge, even though every other dispatch reason on that run was already `info_only`.

The orchestrator already builds `pr_id` deterministically at `scripts/orchestrator_runner.py` — `f"{repo['owner']}/{repo['name']}#{pr['number']}"` — and passes it into the gap-detector dispatch. Requiring the LLM subagent to reliably echo that value back was fragile: an omission or a mangled echo turned orchestrator-owned identity into a point of failure the model had no reason to own reliably.

## Decision

`dispatch_validated` (`scripts/orchestrator_runner.py:dispatch_validated`) gained an optional keyword parameter, `inject: dict | None = None`. After `dispatch_subagent` returns and before `validate_and_parse` runs, the function merges `{**raw, **inject}` — guarded by `isinstance(raw, dict)` — so orchestrator-owned fields override whatever the agent returned:

```python
if inject and isinstance(raw, dict):
    raw = {**raw, **inject}
from contracts import validate_and_parse

validated, reasons = validate_and_parse(name, raw)
```

The gap-detector call site (`scripts/orchestrator_runner.py`) is the only caller that passes `inject`:

```python
verdict, reasons = dispatch_validated(
    "gap-detector",
    {
        "pr_id": pr_id,
        "pr": pr,
        "config": {...},
        "dismissed_flags": list(dismissed),
    },
    dry_run_dir=dry_run_dir,
    cwd=repo_root,
    inject={"pr_id": pr_id},  # CCE-120: orchestrator-authoritative identity
)
```

The input payload still carries `"pr_id": pr_id` for agent context, but the schema requirement is now satisfied by the injected copy regardless of whether the agent echoes it back correctly, at all, or with the wrong value.

`needs_spec` — the agent's actual judgment call — stays required and untouched. A verdict that omits `needs_spec` still fails schema validation and still flips the run to `partial`; this fix only removes `pr_id` as a source of LLM-echo fragility.

## Why injection, not schema relaxation

Two other approaches were considered and rejected:

- **Relax the schema and give `GapVerdict.pr_id` a default.** Conceptually cleaner (the field would truly leave agent-owned territory), but it touches four surfaces and forces a field reorder on the frozen `GapVerdict` dataclass (`scripts/contracts.py`) — `needs_spec` would have to precede any newly-defaulted field. Higher churn and risk for the same outcome.
- **Prompt-harden the agent to always emit `pr_id`.** Non-deterministic; it doesn't remove the underlying fragility, just makes the failure rarer.

Injecting at the orchestrator level keeps the schema, the `GapVerdict` dataclass, and the `agents/gap-detector.md` prompt all unchanged, while making `pr_id` always present, always type-valid, and authoritative — it now overrides a wrong echo as well as a missing one.

## Behavior by case

| Condition | Behavior |
| --- | --- |
| Agent omits `pr_id` | injected → schema passes → verdict carries the authoritative `pr_id` |
| Agent echoes a different `pr_id` | injected value overrides it (`{**raw, **inject}`) |
| Agent omits `needs_spec` | still `schema_invalid` → partial (unchanged; this is a real judgment failure) |
| Agent returns a non-dict response | injection skipped by the `isinstance` guard → normal schema rejection (unchanged) |
| Any other `dispatch_validated` caller (`inject=None`) | merge skipped → identical to prior behavior |

`dispatch_validated` has seven other call sites in the orchestrator; none of them pass `inject`, so `inject=None` is a pure pass-through for all of them.

## Test coverage map

| Test file | What it pins |
| --- | --- |
| `tests/orchestrator/test_dispatch_validated_inject.py` | `inject` fills a missing `pr_id`; `inject` overrides a wrong echoed `pr_id`; `inject=None` is unchanged behavior, including still rejecting a missing `pr_id` with no injection |
| `tests/orchestrator/test_gap_detector_prid_injection.py` | End-to-end through the real `run()`: a gap-detector fixture missing `pr_id` no longer flips the run `partial`, and the injected `pr_id` renders into the What's-New "Gaps flagged" block; a fixture missing `needs_spec` still flips `partial` (regression guard) |

The integration test drives the fix through the ordinary dry-run fixture path — no monkeypatching — by copying every `fake_*.json` from `tests/orchestrator/fakes/` and overwriting only `fake_gap_detector.json`.

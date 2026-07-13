# CCE-120: orchestrator injects its own `pr_id` into the gap-detector verdict — design

**Date:** 2026-07-12
**Ticket:** [CCE-120](https://designitright.atlassian.net/browse/CCE-120)
**Status:** approved (A2, brainstormed 2026-07-12)
**Fix surface:** in-repo (`scripts/orchestrator_runner.py` + tests). Ships via the plugin.

## Problem

`gap_detector.schema.json` lists `required: ["pr_id", "needs_spec"]`, so `validate_and_parse`
(`scripts/contracts.py:103-116`) rejects any gap-detector verdict missing `pr_id` with
`schema_invalid: gap-detector: 'pr_id' is a required property`. That reason flips the nightly
run to `partial` (the gap-detector callsite records dispatch failures as partial-flipping),
which blocks CCE-101 auto-merge.

But the orchestrator **constructs `pr_id` itself** — `scripts/orchestrator_runner.py:1806`:
`pr_id = f"{repo['owner']}/{repo['name']}#{pr['number']}"` — and passes it _into_ the dispatch,
then requires the LLM to echo it _back_. `pr_id` is orchestrator-owned identity; making the
LLM its source of truth is fragile.

**Evidence:** nightly PR #173 (2026-07-12), the first run carrying the CCE-118 fix, was partial
for exactly one reason: `schema_invalid: gap-detector: 'pr_id' is a required property`. Every
other reason (`prose_contamination_rescued: fact-checker`) was already `info_only`. So this is
the current sole blocker to a clean, auto-mergeable nightly.

## Validation mechanics (confirmed)

`validate_and_parse(name, raw)` enforces two layers:

1. **JSON Schema** — `jsonschema.validate(raw, schema)`; missing `pr_id` → `ValidationError` →
   `(None, ["schema_invalid: gap-detector: 'pr_id' is a required property"])`. **This is the
   failing layer.**
2. **Dataclass** — `GapVerdict(pr_id: str, needs_spec: bool, reasoning="", confidence="medium",
tier="llm")`. `cls(**kwargs)` is only reached _after_ the schema passes, so today it never
   sees a missing `pr_id`.

`dispatch_validated` returns the **raw dict** (not the dataclass), so the orchestrator and
downstream consumers read `verdict["pr_id"]` (`:1847`, `:1994`).

## Decision — A2: inject the orchestrator-owned field before validation

Add an optional `inject: dict | None = None` parameter to `dispatch_validated`. After the
dispatch returns a dict and **before** validation, merge `{**raw, **inject}` so
orchestrator-owned fields **override** the agent's echo. The gap-detector call passes
`inject={"pr_id": pr_id}`.

### Why A2 over the alternatives

| Approach                      | Verdict    | Reason                                                                                                                                                                                                                                                                          |
| ----------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A2 — inject at dispatch**   | **chosen** | 2 lines + 1 call-site arg. Optional param → backward-compatible (the other 7 callers unchanged). Schema, `GapVerdict`, and the agent prompt untouched. `pr_id` stays type-validated and self-identifying, now always present and authoritative (also overrides a _wrong_ echo). |
| A1 — relax schema + dataclass | rejected   | Conceptually pure (pr_id leaves the agent output) but touches 4 surfaces and forces a frozen-dataclass field reorder (`needs_spec` must precede any defaulted field) — higher churn/risk for the same outcome.                                                                  |
| A3 — prompt-harden the LLM    | rejected   | Non-deterministic; doesn't remove the fragility. (This is the out-of-scope "Fix C".)                                                                                                                                                                                            |

**Scope: Fix A only.** `needs_spec` (the agent's actual judgment) stays required — a genuinely
empty verdict still correctly flips partial. The advisory-posture change (Fix B: gap-detector
failures → `info_only`) is deliberately **out of scope**.

## Architecture

`scripts/orchestrator_runner.py`, `dispatch_validated`:

```python
def dispatch_validated(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
    inject: dict | None = None,
) -> tuple[dict | None, list[str]]:
    dispatch_reasons: list[str] = []
    raw = dispatch_subagent(
        name, inputs, dry_run_dir=dry_run_dir, cwd=cwd, out_reasons=dispatch_reasons
    )
    if raw is None:
        return None, dispatch_reasons
    # CCE-120: stamp orchestrator-owned fields (e.g. pr_id) before validation so a
    # value the orchestrator already owns is never sourced from the LLM's echo.
    # inject wins over the agent's own value (authoritative + defends a wrong echo).
    if inject and isinstance(raw, dict):
        raw = {**raw, **inject}
    from contracts import validate_and_parse
    validated, reasons = validate_and_parse(name, raw)
    if validated is None:
        return None, dispatch_reasons + reasons
    return raw, dispatch_reasons
```

Gap-detector call site (`~:1809`):

```python
verdict, reasons = dispatch_validated(
    "gap-detector",
    {..., "pr_id": pr_id, ...},          # unchanged input payload
    dry_run_dir=dry_run_dir,
    cwd=repo_root,
    inject={"pr_id": pr_id},             # CCE-120: orchestrator-authoritative identity
)
```

The `isinstance(raw, dict)` guard keeps a non-dict agent response (e.g. a JSON list) falling
through to normal schema rejection — unchanged behavior.

## Edge cases / degradation

| Condition                          | Behavior                                                             |
| ---------------------------------- | -------------------------------------------------------------------- |
| Agent omits `pr_id`                | injected → schema passes → verdict carries the authoritative `pr_id` |
| Agent echoes a _different_ `pr_id` | injected value overrides it (`{**raw, **inject}`)                    |
| Agent omits `needs_spec`           | still `schema_invalid` → partial (real judgment failure, unchanged)  |
| Agent returns a non-dict           | injection skipped → schema rejects (unchanged)                       |
| Any other caller (`inject=None`)   | merge skipped → identical to today                                   |

## Testing (TDD, fixture-driven dry-run path)

1. **Unit — `dispatch_validated` inject** (monkeypatch `subprocess.run`, production path):
   - a gap-detector response _missing_ `pr_id` + `inject={"pr_id": X}` → returns a verdict with `pr_id == X`, no `schema_invalid`;
   - a response echoing a _wrong_ `pr_id` + inject → returns the **injected** value (override);
   - `inject=None` → behavior identical to today (regression for the 7 other callers).
2. **Integration — real `run()`, RED→GREEN** (mirrors the CCE-118 `dispatch_validated`-spy harness):
   a gap-detector fixture that omits `pr_id` currently flips the run `partial`
   (`schema_invalid: gap-detector`); after the fix the run is **non-partial** and the recorded
   verdict downstream carries the correct `pr_id`.
3. **Regression:** a gap-detector fixture missing `needs_spec` still flips `partial` — Fix A must
   not swallow genuine judgment failures.
4. Full `python3 -m pytest` green.

## Acceptance criteria (mapped to ticket)

1. A gap-detector verdict missing `pr_id` no longer flips the run to partial; the returned
   verdict carries the orchestrator's authoritative `pr_id`. _(AC 1)_
2. An injected `pr_id` overrides a differing value echoed by the agent. _(AC 2)_
3. A verdict missing `needs_spec` still flips partial. _(AC 3)_
4. `inject=None` leaves all other dispatch callers unchanged. _(AC 4)_
5. Verifiable on the next nightly: a run whose only prior blocker was
   `schema_invalid: gap-detector: 'pr_id'` reaches non-partial. _(AC 5 — observational.)_

## Out of scope

- Fix B (advisory posture: gap-detector dispatch failures → `info_only`) — a separate design
  decision; this fix keeps genuine gap-detector failures blocking.
- The gap-detector prompt / `agents/gap-detector.md` — unchanged; the agent may still emit
  `pr_id` (harmlessly overridden) or omit it.
- Schema / `GapVerdict` dataclass — unchanged.

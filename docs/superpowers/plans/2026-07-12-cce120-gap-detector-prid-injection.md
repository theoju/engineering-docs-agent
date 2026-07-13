# CCE-120: Orchestrator-injected gap-detector `pr_id` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the nightly run flipping to `partial` when the gap-detector agent omits `pr_id` — the orchestrator already owns that field, so it injects it into the verdict before schema validation instead of requiring the LLM to echo it back.

**Architecture:** Add an optional `inject: dict | None = None` parameter to `dispatch_validated` (`scripts/orchestrator_runner.py`). After the subagent returns a dict and **before** `validate_and_parse`, merge `{**raw, **inject}` so orchestrator-owned fields override the agent's echo. The single gap-detector call site passes `inject={"pr_id": pr_id}`. Schema, the `GapVerdict` dataclass, and the agent prompt are untouched. This is Fix A / approach A2 from the spec — `needs_spec` (the agent's real judgment) stays required.

**Tech Stack:** Python 3 (stdlib-first), pytest, fixture-driven dry-run path (`dispatch_subagent` loads `fake_<name>.json` from `dry_run_dir`; the production `claude` CLI dispatch is never invoked in tests).

**Spec:** `docs/superpowers/specs/2026-07-12-cce120-gap-detector-prid-injection-design.md` (committed `54369b5`).

**Branch:** `fix/CCE-120-gap-detector-prid-injection` (off `main`; spec already committed).

---

## Background the implementer needs

`dispatch_validated(name, inputs, *, dry_run_dir, cwd=None)` (`scripts/orchestrator_runner.py:732`) composes two calls:

1. `raw = dispatch_subagent(...)` — in dry-run, this returns the parsed contents of `dry_run_dir / f"fake_{name.replace('-', '_')}.json"` **directly** (`orchestrator_runner.py:616-620`). It returns `None` when the fixture is missing / the agent failed.
2. `validated, reasons = validate_and_parse(name, raw)` (`scripts/contracts.py:103`) — layer 1 runs `jsonschema.validate(raw, schema)`; a missing required property raises `ValidationError` → returns `(None, ["schema_invalid: <name>: '<prop>' is a required property"])`. Layer 2 (dataclass construction) only runs if the schema passes.

`dispatch_validated` returns the **raw dict** (not the dataclass) so call sites keep using `dict.get()` patterns. When `validated is None`, it returns `(None, dispatch_reasons + reasons)`.

The gap-detector call site (`orchestrator_runner.py:1806-1832`):

```python
pr_id = f"{repo['owner']}/{repo['name']}#{pr['number']}"
if pr_id in dismissed:
    continue
verdict, reasons = dispatch_validated(
    "gap-detector",
    {
        "pr_id": pr_id,
        "pr": pr,
        "config": { ... },
        "dismissed_flags": list(dismissed),
    },
    dry_run_dir=dry_run_dir,
    cwd=repo_root,
)
_record_dispatch_reasons(state, reasons, ok=verdict is not None)
if verdict is None:
    if not reasons:
        add_partial(state, f"gap_detector_invalid: pr_id={pr_id}")
    continue
gap_verdicts.append(verdict)
```

`_record_dispatch_reasons(state, reasons, ok=False)` flips `partial` for every reason (CCE-118). So a `schema_invalid: gap-detector: 'pr_id'` reason today flips the run to `partial`, blocking CCE-101 auto-merge. The orchestrator **constructs `pr_id` itself** (line 1806) and passes it _in_ — requiring the agent to echo it back is the fragility this fix removes.

Downstream, the verdict's `pr_id` is read at `orchestrator_runner.py:1847` (`f"- {g['pr_id']}: {g['reasoning']}"` in the What's-New "Gaps flagged" block) and `:1994`.

**Schema (`agents/schemas/gap_detector.schema.json`) stays unchanged:** `required: ["pr_id", "needs_spec"]`. Injecting `pr_id` before validation satisfies the `pr_id` requirement without touching the schema; `needs_spec` stays required so a genuinely empty verdict still (correctly) flips partial.

**GapVerdict dataclass (`scripts/contracts.py:51`) stays unchanged:** `pr_id: str; needs_spec: bool; reasoning=""; confidence="medium"; tier="llm"`. (Approach A1 — giving `pr_id` a default — was rejected precisely to avoid the frozen-dataclass field reorder.)

---

## File Structure

- **Modify:** `scripts/orchestrator_runner.py`
  - `dispatch_validated` (line 732): add the `inject` parameter + pre-validation merge.
  - gap-detector call site (line ~1809): pass `inject={"pr_id": pr_id}`.
- **Create:** `tests/orchestrator/test_dispatch_validated_inject.py` — unit tests for the `inject` mechanism (dry-run fixture path, no monkeypatching).
- **Create:** `tests/orchestrator/test_gap_detector_prid_injection.py` — integration RED→GREEN through the real `run()`, plus the `needs_spec` regression guard.

Two tasks. Task 1 delivers and unit-tests the generic mechanism; Task 2 wires the single call site and proves the end-to-end fix through `run()`.

---

### Task 1: Add `inject` parameter to `dispatch_validated`

**Files:**

- Modify: `scripts/orchestrator_runner.py:732-765` (`dispatch_validated`)
- Test: `tests/orchestrator/test_dispatch_validated_inject.py` (create)

The unit tests drive `dispatch_validated` through the **dry-run fixture path**: write a `fake_gap_detector.json` into a tmp dir and pass it as `dry_run_dir`. `dispatch_subagent` returns that dict verbatim, so the test exercises the real `inject` merge with zero monkeypatching.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/orchestrator/test_dispatch_validated_inject.py`:

```python
"""CCE-120: dispatch_validated(..., inject={...}) stamps orchestrator-owned
fields onto the raw agent output BEFORE schema validation, so a value the
orchestrator already owns (e.g. gap-detector's pr_id) is never sourced from
the LLM's echo. inject wins over the agent's own value.

These tests use the dry-run fixture path: dispatch_subagent returns the
fake_<name>.json contents verbatim, so the real inject merge runs unmocked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402


def _write_gap_fixture(dry_run_dir: Path, payload: dict) -> None:
    dry_run_dir.mkdir(parents=True, exist_ok=True)
    (dry_run_dir / "fake_gap_detector.json").write_text(json.dumps(payload))


def test_inject_fills_missing_prid(tmp_path):
    # Agent output omits pr_id (the CCE-120 failure). Schema requires it.
    _write_gap_fixture(tmp_path, {"needs_spec": True, "reasoning": "why"})
    out, reasons = runner.dispatch_validated(
        "gap-detector",
        {},
        dry_run_dir=tmp_path,
        inject={"pr_id": "owner/repo#7"},
    )
    assert reasons == []
    assert out is not None
    assert out["pr_id"] == "owner/repo#7"
    assert out["needs_spec"] is True


def test_inject_overrides_wrong_prid(tmp_path):
    # Agent echoes a DIFFERENT pr_id; the injected value must win.
    _write_gap_fixture(
        tmp_path, {"pr_id": "WRONG#1", "needs_spec": False, "reasoning": "x"}
    )
    out, reasons = runner.dispatch_validated(
        "gap-detector",
        {},
        dry_run_dir=tmp_path,
        inject={"pr_id": "owner/repo#7"},
    )
    assert reasons == []
    assert out["pr_id"] == "owner/repo#7"


def test_inject_none_is_unchanged_behavior(tmp_path):
    # Regression for the 7 other callers: no inject => today's behavior.
    # A valid verdict passes through untouched...
    _write_gap_fixture(
        tmp_path, {"pr_id": "owner/repo#7", "needs_spec": True, "reasoning": "x"}
    )
    out, reasons = runner.dispatch_validated("gap-detector", {}, dry_run_dir=tmp_path)
    assert reasons == []
    assert out["pr_id"] == "owner/repo#7"


def test_inject_none_still_rejects_missing_prid(tmp_path):
    # ...and a verdict missing pr_id with NO inject still fails schema
    # validation exactly as before (inject didn't secretly fix anything).
    _write_gap_fixture(tmp_path, {"needs_spec": True, "reasoning": "x"})
    out, reasons = runner.dispatch_validated("gap-detector", {}, dry_run_dir=tmp_path)
    assert out is None
    assert any(r.startswith("schema_invalid: gap-detector") for r in reasons), reasons
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_dispatch_validated_inject.py -v`
Expected: `test_inject_fills_missing_prid`, `test_inject_overrides_wrong_prid`, and `test_inject_none_still_rejects_missing_prid` behavior depends on the new param. The two `inject=`-passing tests FAIL with `TypeError: dispatch_validated() got an unexpected keyword argument 'inject'`. (`test_inject_none_*` may already pass — they exercise existing behavior; that's fine.)

- [ ] **Step 3: Implement the `inject` parameter and pre-validation merge**

In `scripts/orchestrator_runner.py`, edit `dispatch_validated`. Add the parameter to the signature and the merge block. The full updated function:

```python
def dispatch_validated(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
    inject: dict | None = None,
) -> tuple[dict | None, list[str]]:
    """Compose dispatch_subagent with validate_and_parse.

    Returns:
      Schema-valid clean:           (raw_dict, [])
      Schema-valid + rescued (CCE-15):
                                    (raw_dict, ["prose_contamination_rescued: <name>"])
      Schema-invalid:               (None, [...reasons including any rescue tag])
      Dispatch-None:                (None, []) — caller adds its own generic reason
      Schema-missing:               (None, ["schema_missing: <name>"])

    ``inject`` (CCE-120): orchestrator-owned fields to stamp onto the raw
    agent output BEFORE validation. ``inject`` values override the agent's
    echo (``{**raw, **inject}``), so a field the orchestrator already owns
    (e.g. gap-detector's ``pr_id``) is authoritative and never depends on the
    LLM reproducing it. ``inject=None`` is a pure pass-through — the other
    call sites are unaffected. Only applied when ``raw`` is a dict; a non-dict
    agent response falls through to normal schema rejection unchanged.
    """
    # CCE-15: pass an out_reasons collector so dispatch_subagent can
    # surface prose-contamination rescue events; merge them into the
    # tuple returned to callers (orchestrator state accumulates them
    # into state['current_run']['partial_reasons']).
    dispatch_reasons: list[str] = []
    raw = dispatch_subagent(
        name, inputs, dry_run_dir=dry_run_dir, cwd=cwd, out_reasons=dispatch_reasons
    )
    if raw is None:
        return None, dispatch_reasons
    # CCE-120: stamp orchestrator-owned fields (e.g. pr_id) before validation
    # so a value the orchestrator already owns is never sourced from the LLM's
    # echo. inject wins over the agent's own value (authoritative + defends a
    # wrong echo). The isinstance guard leaves a non-dict response to normal
    # schema rejection.
    if inject and isinstance(raw, dict):
        raw = {**raw, **inject}
    from contracts import validate_and_parse

    validated, reasons = validate_and_parse(name, raw)
    if validated is None:
        return None, dispatch_reasons + reasons
    # Return raw (not the dataclass) so call sites can keep using dict.get() patterns.
    return raw, dispatch_reasons
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_dispatch_validated_inject.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Run the full suite to confirm no regression on the other 7 callers**

Run: `python3 -m pytest -q`
Expected: full suite green (same pass/skip counts as before this task; no new failures). The 7 other `dispatch_validated` call sites pass no `inject`, so `inject=None` leaves them identical.

- [ ] **Step 6: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_validated_inject.py
git commit -m "feat(CCE-120): dispatch_validated injects orchestrator-owned fields pre-validation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Wire the gap-detector call site and prove the end-to-end fix

**Files:**

- Modify: `scripts/orchestrator_runner.py:1809-1826` (gap-detector `dispatch_validated` call)
- Test: `tests/orchestrator/test_gap_detector_prid_injection.py` (create)

The integration test runs the real `run()` against a dry-run fixture directory in which **only** `fake_gap_detector.json` is altered to omit `pr_id`. All other fixtures are copied verbatim from `tests/orchestrator/fakes/` so the pipeline reaches the gap loop. In the test host (no git remote), the orchestrator resolves `pr_id = "unknown/unknown#1"` (matching the committed fixture's own `pr_id` value), and `needs_spec: true` routes it into the What's-New "Gaps flagged" block — giving an observable downstream assertion that the injected `pr_id` reached the verdict.

- [ ] **Step 1: Write the failing integration test + the regression guard**

Create `tests/orchestrator/test_gap_detector_prid_injection.py`:

```python
"""CCE-120: the orchestrator injects its own pr_id into the gap-detector
verdict, so a gap-detector response missing pr_id no longer flips the nightly
run to `partial` (which would block CCE-101 auto-merge). A verdict missing
`needs_spec` — the agent's real judgment — still flips partial.

Integration via the real run(): a custom dry_run_dir copies every fake_*.json
from tests/orchestrator/fakes/ verbatim, then overwrites fake_gap_detector.json
so it omits pr_id. No monkeypatching — the inject merge lives in
dispatch_validated on the ordinary dry-run path.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

FAKES = Path(__file__).parent / "fakes"

# A full-pipeline config that reaches the gap loop (source-collector returns a
# PR; the gap loop iterates every PR). Mirrors the CCE-118 integration config.
GAP_CONFIG = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/core
site:
  docs_dir: docs/site-src
  sections:
    - {key: core, path: core/, title: Core, generator: agent-authored}
sources:
  git: { host: github }
trigger: { cron: "0 7 * * *", on_pr_merge: false }
gap_detection:
  allowlist_paths: ["backend/connectors/**"]
  size_filter: { min_loc: 50, min_files: 3 }
lint: { tier1: default, tier2: {}, tier3: {} }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""

_SEED_STATE = {"version": "1", "dismissed_gap_flags": {}, "cursors": {}}


def _fakes_with_gap(tmp_path: Path, gap_payload: dict) -> Path:
    """Copy all fixtures into tmp, overriding fake_gap_detector.json."""
    d = tmp_path / "fakes"
    shutil.copytree(FAKES, d)
    (d / "fake_gap_detector.json").write_text(json.dumps(gap_payload))
    return d


def test_missing_prid_does_not_flip_partial_and_prid_flows_downstream(
    tmp_path, init_host, read_current_run
):
    state_path = init_host(_SEED_STATE, config_yaml=GAP_CONFIG)
    # gap-detector verdict OMITS pr_id (the CCE-120 failure); needs_spec True
    # so the flagged gap surfaces in What's-New with its pr_id.
    dry = _fakes_with_gap(
        tmp_path, {"needs_spec": True, "reasoning": "allowlist hit", "tier": "allowlist"}
    )
    import orchestrator_runner as runner

    rc = runner.run(tmp_path, dry_run_dir=dry, no_pr=True)
    assert rc == 0

    cr = read_current_run(state_path)
    # The whole point: a missing pr_id is injected, so no schema_invalid, so
    # the run is NOT partial on account of the gap detector.
    assert not any(
        "gap-detector" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert cr["partial"] is False, cr["partial_reasons"]

    # Downstream proof: the injected pr_id reached the verdict and rendered
    # into the What's-New "Gaps flagged" block. In a remote-less test host the
    # orchestrator resolves pr_id to "unknown/unknown#1".
    whats_new = (tmp_path / "docs" / "site-src" / "whats-new.md").read_text()
    assert "unknown/unknown#1" in whats_new, whats_new


def test_missing_needs_spec_still_flips_partial(
    tmp_path, init_host, read_current_run
):
    state_path = init_host(_SEED_STATE, config_yaml=GAP_CONFIG)
    # needs_spec is the agent's real judgment. Omitting it is a genuine
    # failure that MUST still flip partial (Fix A must not swallow it).
    # pr_id present so ONLY the needs_spec gap is under test.
    dry = _fakes_with_gap(
        tmp_path, {"pr_id": "unknown/unknown#1", "reasoning": "x"}
    )
    import orchestrator_runner as runner

    rc = runner.run(tmp_path, dry_run_dir=dry, no_pr=True)
    assert rc == 0

    cr = read_current_run(state_path)
    assert any(
        "schema_invalid: gap-detector" in r and "needs_spec" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert cr["partial"] is True
```

- [ ] **Step 2: Run the tests to verify the RED state**

Run: `python3 -m pytest tests/orchestrator/test_gap_detector_prid_injection.py -v`
Expected:

- `test_missing_prid_does_not_flip_partial_and_prid_flows_downstream` **FAILS** — the call site does not yet pass `inject`, so the missing `pr_id` triggers `schema_invalid: gap-detector: 'pr_id' is a required property`, `_record_dispatch_reasons(..., ok=False)` flips `partial`, and the assertion `cr["partial"] is False` fails.
- `test_missing_needs_spec_still_flips_partial` **PASSES** already — it's the regression guard that must stay green through the fix.

- [ ] **Step 3: Wire `inject={"pr_id": pr_id}` into the gap-detector call site**

In `scripts/orchestrator_runner.py`, the gap-detector `dispatch_validated` call (starts at line ~1809). Add the `inject` argument. The updated call:

```python
            verdict, reasons = dispatch_validated(
                "gap-detector",
                {
                    "pr_id": pr_id,
                    "pr": pr,
                    "config": {
                        "allowlist_paths": config.get("gap_detection", {}).get(
                            "allowlist_paths", []
                        ),
                        "size_filter": config.get("gap_detection", {}).get(
                            "size_filter", {}
                        ),
                    },
                    "dismissed_flags": list(dismissed),
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
                inject={"pr_id": pr_id},  # CCE-120: orchestrator-authoritative identity
            )
```

Only the `inject={"pr_id": pr_id}` line is added; the existing `"pr_id": pr_id` inside the input payload stays (the agent still receives it as context — the schema requirement is now satisfied by the injected copy regardless of whether the agent echoes it).

- [ ] **Step 4: Run the tests to verify GREEN**

Run: `python3 -m pytest tests/orchestrator/test_gap_detector_prid_injection.py -v`
Expected: both tests PASS. The missing-`pr_id` verdict is now injected → schema passes → non-partial → `unknown/unknown#1` renders in What's-New; the missing-`needs_spec` verdict still flips partial.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: full suite green (prior pass count + the 6 new tests from Tasks 1–2; same skip count; no failures).

- [ ] **Step 6: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_gap_detector_prid_injection.py
git commit -m "fix(CCE-120): inject orchestrator-owned pr_id into the gap-detector verdict

The nightly flipped to partial whenever the gap-detector agent omitted pr_id
(schema_invalid: gap-detector: 'pr_id' is a required property), blocking
CCE-101 auto-merge. pr_id is orchestrator-owned identity, so the call site now
injects it before validation instead of requiring the LLM to echo it back.
needs_spec stays required — a genuinely empty verdict still flips partial.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage** — each spec section maps to a task:

| Spec element                                                                              | Where implemented                                                                                                                                           |
| ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A2: `inject` param + `{**raw, **inject}` before validation, `isinstance(raw, dict)` guard | Task 1, Step 3                                                                                                                                              |
| Gap-detector call passes `inject={"pr_id": pr_id}`                                        | Task 2, Step 3                                                                                                                                              |
| AC 1: missing `pr_id` no longer flips partial; verdict carries authoritative `pr_id`      | Task 2 `test_missing_prid_..._flows_downstream`                                                                                                             |
| AC 2: injected `pr_id` overrides a differing echo                                         | Task 1 `test_inject_overrides_wrong_prid`                                                                                                                   |
| AC 3: missing `needs_spec` still flips partial                                            | Task 2 `test_missing_needs_spec_still_flips_partial`                                                                                                        |
| AC 4: `inject=None` leaves other callers unchanged                                        | Task 1 `test_inject_none_is_unchanged_behavior` + `test_inject_none_still_rejects_missing_prid` + full-suite green                                          |
| AC 5: verifiable on next nightly (observational)                                          | Post-ship; not a code task                                                                                                                                  |
| Out of scope: schema / `GapVerdict` / agent prompt / Fix B                                | No task touches them (asserted by full-suite green)                                                                                                         |
| Edge: non-dict agent response falls through to schema rejection                           | Guarded by `isinstance(raw, dict)`; covered by the `test_inject_none_still_rejects_missing_prid` schema-rejection path and the unchanged rejection behavior |

**2. Placeholder scan** — no TBD/TODO; every code step shows complete code; every run step shows the exact command and expected outcome.

**3. Type consistency** — `dispatch_validated` keeps its `tuple[dict | None, list[str]]` return; the new `inject: dict | None = None` param name is used identically in the signature, the call site, and all tests. `pr_id` string form `"owner/repo#7"` / `"unknown/unknown#1"` is consistent with the existing fixture and the `f"{repo['owner']}/{repo['name']}#{pr['number']}"` construction.

---

## Execution Handoff

Execute with **superpowers:subagent-driven-development** (fresh subagent per task, spec-compliance then code-quality review after each, controller discharges each implementer's claims against the actual git tree + real pytest per the CLAUDE.md declare-then-discharge fidelity gate). Tests run with `python3 -m pytest` from the repo root.

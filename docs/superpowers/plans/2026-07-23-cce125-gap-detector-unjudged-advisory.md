# CCE-125 — gap-detector unjudged advisory-skip Implementation Plan

> **For agentic workers:** TDD, one failing test → implementation → green → commit per task. Steps use `- [ ]`.

**Goal:** A gap-detector verdict of `needs_spec: null` ("couldn't judge") stops flipping the nightly run to partial; it becomes an info-only advisory skip. Genuine structural failures (absent key / wrong type / unparseable) still flip partial.

**Architecture:** Widen the gap-detector schema so `null` is a valid `needs_spec`; a validated null verdict is recorded info-only (`gap_detector_unjudged`) and skipped at the orchestrator callsite. Deterministic — independent of LLM behavior.

**Tech Stack:** Python stdlib + jsonschema; pytest; fixture-driven dry-run (Claude CLI dispatch monkeypatched).

---

### Task 1: Schema accepts null + dataclass relaxed (contracts)

**Files:**

- Modify: `agents/schemas/gap_detector.schema.json:8`
- Modify: `agents/gap-detector.md:35` (canonical block, in lockstep)
- Modify: `scripts/contracts.py:54`
- Test: `tests/contracts/test_contracts.py`

- [ ] **Step 1 — Failing tests.** Add to `tests/contracts/test_contracts.py`:

```python
def test_gap_detector_null_needs_spec_is_valid_unjudged():
    from scripts.contracts import GapVerdict, validate_and_parse

    obj, errors = validate_and_parse(
        "gap-detector", {"pr_id": "o/r#1", "needs_spec": None}
    )
    assert errors == []
    assert isinstance(obj, GapVerdict)
    assert obj.needs_spec is None


def test_gap_detector_absent_needs_spec_still_invalid():
    from scripts.contracts import validate_and_parse

    obj, errors = validate_and_parse("gap-detector", {"pr_id": "o/r#1"})
    assert obj is None
    assert any("needs_spec" in e for e in errors)


def test_gap_detector_wrong_type_needs_spec_still_invalid():
    from scripts.contracts import validate_and_parse

    obj, errors = validate_and_parse(
        "gap-detector", {"pr_id": "o/r#1", "needs_spec": "yes"}
    )
    assert obj is None
    assert any("schema_invalid" in e for e in errors)
```

- [ ] **Step 2 — Run, expect FAIL** on `test_gap_detector_null_needs_spec_is_valid_unjudged` (`None is not of type 'boolean'`).

Run: `.venv/bin/python -m pytest tests/contracts/test_contracts.py -q`

- [ ] **Step 3 — Implement.**
  - `agents/schemas/gap_detector.schema.json:8`: `"needs_spec": { "type": ["boolean", "null"] },`
  - `agents/gap-detector.md:35` (canonical fenced block): `"needs_spec": { "type": ["boolean", "null"] },`
  - `scripts/contracts.py:54`: `needs_spec: bool | None`

- [ ] **Step 4 — Run, expect PASS** (all three new tests + existing `test_gap_detector_validates_and_parses` + `tests/agents/test_schema_md_sync.py`).

Run: `.venv/bin/python -m pytest tests/contracts/test_contracts.py tests/agents/test_schema_md_sync.py -q`

- [ ] **Step 5 — Commit.** `git commit -am "feat(CCE-125): gap-detector schema accepts null needs_spec (unjudged)"`

---

### Task 2: Orchestrator records null as info-only and skips it

**Files:**

- Modify: `scripts/orchestrator_runner.py` (between the `if verdict is None` block at `:1900-1903` and `gap_verdicts.append(verdict)` at `:1904`)
- Test: `tests/orchestrator/test_gap_detector_unjudged.py` (new)

- [ ] **Step 1 — Failing test.** New file `tests/orchestrator/test_gap_detector_unjudged.py` that drives a dry-run with a gap-detector fixture whose `needs_spec` is `null`, asserting: `state["current_run"]["partial"] is False`; a `gap_detector_unjudged: pr_id=…` reason is present in `partial_reasons`; the What's New has no "Gaps flagged" entry for that PR. Add a sibling asserting an **absent** `needs_spec` fixture yields `partial is True`. Mirror the harness in `tests/orchestrator/test_gap_detector_prid_injection.py` (fixture layout, `run()` invocation, dry-run dir).

- [ ] **Step 2 — Run, expect FAIL** — the null run currently flips partial (schema_invalid) or, post-Task-1, appends the null verdict without emitting the info-only reason.

Run: `.venv/bin/python -m pytest tests/orchestrator/test_gap_detector_unjudged.py -q`

- [ ] **Step 3 — Implement.** Insert between `:1903` `continue` and `:1904`:

```python
            if verdict.get("needs_spec") is None:
                add_partial(
                    state,
                    f"gap_detector_unjudged: pr_id={pr_id}",
                    info_only=True,
                )
                continue
```

- [ ] **Step 4 — Run, expect PASS** (new tests + `test_gap_detector_prid_injection.py` unchanged-green).

Run: `.venv/bin/python -m pytest tests/orchestrator/test_gap_detector_unjudged.py tests/orchestrator/test_gap_detector_prid_injection.py -q`

- [ ] **Step 5 — Commit.** `git commit -am "feat(CCE-125): orchestrator records null gap verdict info-only, skips it"`

---

### Task 3: Prompt align + regenerate contract doc

**Files:**

- Modify: `agents/gap-detector.md:74` (failure-handling)
- Modify: `docs/site-src/api/contracts/gap_detector.schema.md` (regenerate)

- [ ] **Step 1 — Prompt.** `agents/gap-detector.md:74` — keep the `needs_spec: null` fallback and document it as the valid "couldn't judge" sentinel, e.g.: `If inputs are malformed and you cannot judge, return {"error": "malformed_input", "needs_spec": null} — null is the valid "unjudged" value; the run records it as advisory and does not fail.`

- [ ] **Step 2 — Regenerate the contract doc.** Discover the CLI (`.venv/bin/python scripts/contracts_doc.py --help`), regenerate so the `needs_spec` row reads `boolean | null`. If it writes in place, confirm the git diff touches only that row.

- [ ] **Step 3 — Verify consumer tool.** `tests/agents/test_schema_md_sync.py` and any `contracts_doc` tests green.

Run: `.venv/bin/python -m pytest tests/agents tests/contracts -q`

- [ ] **Step 4 — Commit.** `git commit -am "docs(CCE-125): document null unjudged sentinel + regenerate contract doc"`

---

### Task 4: Fact-checker regression lock-test (additive)

**Files:**

- Test: `tests/orchestrator/test_fact_checker.py` (add) — or a new sibling.

- [ ] **Step 1 — Characterization/lock test.** Add a test that drives a dry-run where the fact-checker dispatch emits prose-wrapped valid JSON (triggering `prose_contamination_rescued: fact-checker`), asserting `state["current_run"]["partial"] is False` **and** the `prose_contamination_rescued: fact-checker` reason is present in `partial_reasons` (info-only). Point at the fact-checker advisory path specifically — do not duplicate `test_record_dispatch_reasons.py`.

- [ ] **Step 2 — Run, expect PASS on current code** (locks existing CCE-118 behavior; regression guard, not red-green).

Run: `.venv/bin/python -m pytest tests/orchestrator/test_fact_checker.py -q`

- [ ] **Step 3 — Commit.** `git commit -am "test(CCE-125): lock fact-checker prose_contamination_rescued stays info-only"`

---

### Final: full integrated suite + adversarial validation

- [ ] `export PATH="$(pwd)/.venv/bin:$PATH"` then `python -m pytest -q` — expect all green (the 5 `tests/site/*` mkdocs-build tests need `.venv/bin` on PATH; otherwise env-only failures, not regressions).
- [ ] Adversarial validation workflow (correctness / test-non-vacuity / blast-radius) on the CCE-125 diff.
- [ ] `/ship` with `CCE-125` in the PR title.

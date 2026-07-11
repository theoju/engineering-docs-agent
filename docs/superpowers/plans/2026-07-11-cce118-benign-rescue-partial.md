# CCE-118 (item 1): benign rescue must not flip partial — implementation plan

> **For agentic workers:** TDD. Failing test → minimal implementation → green → commit. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A blocking-pipeline dispatch that succeeds via prose-contamination rescue must not flip the run to `partial`.

**Architecture:** One pure helper `_record_dispatch_reasons(state, reasons, *, ok)` in `scripts/orchestrator_runner.py` that records dispatch reasons `info_only=ok`. Five callsites (source-collector, pr-summarizer, page-author, content-validator, gap-detector) switch their `for r in reasons: add_partial(state, r)` loop to the helper, passing `ok=<success_var> is not None`.

**Tech Stack:** Python stdlib, pytest, fixture-driven dry-run path.

Spec: `docs/superpowers/specs/2026-07-11-cce118-benign-rescue-partial-design.md`

---

### Task 1: `_record_dispatch_reasons` helper (unit TDD)

**Files:**

- Modify: `scripts/orchestrator_runner.py` (new helper near `dispatch_validated`)
- Test: `tests/orchestrator/test_record_dispatch_reasons.py` (create)

- [ ] **Step 1 — failing test.** Build a minimal state dict and assert the contract:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner as runner


def _fresh_state():
    return {"current_run": {"partial": False, "partial_reasons": []}}


def test_ok_true_records_info_only_no_partial_flip():
    state = _fresh_state()
    runner._record_dispatch_reasons(
        state, ["prose_contamination_rescued: page-author"], ok=True
    )
    assert state["current_run"]["partial"] is False
    assert "prose_contamination_rescued: page-author" in state["current_run"]["partial_reasons"]


def test_ok_false_flips_partial():
    state = _fresh_state()
    runner._record_dispatch_reasons(
        state, ["schema_invalid: page-author: 'ok' is a required property"], ok=False
    )
    assert state["current_run"]["partial"] is True


def test_empty_reasons_noop():
    state = _fresh_state()
    runner._record_dispatch_reasons(state, [], ok=True)
    assert state["current_run"]["partial"] is False
    assert state["current_run"]["partial_reasons"] == []
```

- [ ] **Step 2 — run, expect fail** (`AttributeError: _record_dispatch_reasons`). `python3 -m pytest tests/orchestrator/test_record_dispatch_reasons.py -q`
- [ ] **Step 3 — implement** the helper (place next to `dispatch_validated`, after it):

```python
def _record_dispatch_reasons(state: dict, reasons: list[str], *, ok: bool) -> None:
    """Record dispatch_validated reasons onto the run state. (CCE-118)

    A dispatch that returned usable output (ok=True) can only carry benign
    `prose_contamination_rescued` diagnostics — a schema failure forces the
    dispatch output to None — so its reasons are recorded info_only and must
    NOT flip `partial`. When the dispatch failed (ok=False) the reasons explain
    dropped work and DO flip `partial`.

    Advisory layers (fact-checker, deterministic generators) record info_only=True
    directly and do not route through this helper.
    """
    for r in reasons:
        add_partial(state, r, info_only=ok)
```

- [ ] **Step 4 — green.** Rerun; expect PASS.
- [ ] **Step 5 — commit.** `git commit -m "feat(CCE-118): _record_dispatch_reasons helper — benign rescue is info_only"`

---

### Task 2: migrate the five callsites + integration RED→GREEN

**Files:**

- Modify: `scripts/orchestrator_runner.py` lines 1333-1334, 1424-1425, 1549-1550, 1584-1585, 1814-1815
- Test: `tests/orchestrator/test_benign_rescue_not_partial.py` (create)

Replace each `for r in reasons:\n    add_partial(state, r)` with:

- `:1333` → `_record_dispatch_reasons(state, reasons, ok=sources is not None)`
- `:1424` → `_record_dispatch_reasons(state, reasons, ok=summary is not None)`
- `:1549` → `_record_dispatch_reasons(state, reasons, ok=out is not None)`
- `:1584` → `_record_dispatch_reasons(state, reasons, ok=validation is not None)`
- `:1814` → `_record_dispatch_reasons(state, reasons, ok=verdict is not None)`

Leave the `clip_reasons` loop at `:1360-1361` unchanged (not a dispatch rescue).

- [ ] **Step 1 — failing integration test.** Model on `test_agent_authored_create_frontmatter.py`'s `spy` + `run()` harness. Wrap the real `dispatch_validated`, append a rescue reason to the page-author result, drive `run()`, assert non-partial:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

FAKES = Path(__file__).parent / "fakes"
_SEED_STATE = {"version": "1", "dismissed_gap_flags": {}, "cursors": {}}

# reuse the fixture host config that authors a page
from test_agent_authored_create_frontmatter import CONFIG_AGENT_AUTHORED


def _read_partial(tmp_path):
    import json
    state = json.loads((tmp_path / ".engineering-docs-agent" / "state.json").read_text())
    cr = state.get("current_run") or state.get("last_run") or {}
    return cr


def test_benign_page_author_rescue_does_not_flip_partial(tmp_path, init_host, monkeypatch):
    init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    import orchestrator_runner as runner

    orig = runner.dispatch_validated

    def spy(name, payload, **kw):
        out, reasons = orig(name, payload, **kw)
        if name == "page-author":
            reasons = reasons + ["prose_contamination_rescued: page-author"]
        return out, reasons

    monkeypatch.setattr(runner, "dispatch_validated", spy)
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0
    cr = _read_partial(tmp_path)
    assert cr.get("partial") is False, cr.get("partial_reasons")
    assert "prose_contamination_rescued: page-author" in cr.get("partial_reasons", [])


def test_genuine_page_author_failure_still_flips_partial(tmp_path, init_host, monkeypatch):
    init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    import orchestrator_runner as runner

    orig = runner.dispatch_validated

    def spy(name, payload, **kw):
        out, reasons = orig(name, payload, **kw)
        if name == "page-author":
            return None, reasons + ["schema_invalid: page-author: 'ok' is a required property"]
        return out, reasons

    monkeypatch.setattr(runner, "dispatch_validated", spy)
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    cr = _read_partial(tmp_path)
    assert cr.get("partial") is True
```

> **Note for implementer:** confirm the exact on-disk location of the run record and whether it lives under `current_run` or has been promoted to `last_run` after `run()` completes — read `scripts/state_io.py` / `conftest.read_current_run` and adjust `_read_partial` accordingly. Assert on the true post-run shape. If `read_current_run` fixture exposes this, prefer it over hand-rolling the read.

- [ ] **Step 2 — run, expect the benign test to FAIL** (partial is True before the fix), regression test to PASS.
- [ ] **Step 3 — apply the five callsite edits** above.
- [ ] **Step 4 — green.** Both tests pass.
- [ ] **Step 5 — full suite.** `python3 -m pytest -q` — all green (no regression in `test_auto_merge.py`, `test_fact_checker.py`, `test_pipeline_integration.py`).
- [ ] **Step 6 — commit.** `git commit -m "fix(CCE-118): benign dispatch rescue no longer flips run to partial"`

---

### Task 3: CHANGELOG + verify no fact-checker path touched

**Files:**

- Modify: `CHANGELOG.md`

- [ ] **Step 1** — add a `Fixed` entry under the working version: benign `prose_contamination_rescued` on a blocking-pipeline dispatch no longer flips the run to partial (CCE-118); fact-checker advisory reasons and the contradiction-warning gate unchanged.
- [ ] **Step 2** — `grep -n "info_only" scripts/orchestrator_runner.py` and confirm the fact-checker (`:1708/:1713`) and generator advisory sites are untouched.
- [ ] **Step 3 — commit.**

## Self-review

- Spec coverage: AC1 (Task 2 benign test), AC2 (Task 2 regression), AC3 (Task 3 step 2 grep), AC4 (post-merge observational).
- No placeholders. Types consistent (`ok` bool everywhere; `_record_dispatch_reasons` signature stable across tasks).

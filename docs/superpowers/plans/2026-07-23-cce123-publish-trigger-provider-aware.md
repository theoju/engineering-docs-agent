# CCE-123 Publish-Trigger Provider-Aware Dispatch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the post-merge build-_trigger_ seam in `_maybe_auto_merge` provider-aware — github keeps its native `gh.workflow_run` dispatch; a `circleci` host degrades honestly with one `info_only` `pages_dispatch_skipped` reason and no dispatch.

**Architecture:** Mirror the CCE-63 verify seam. A new `build_poller.resolve_build_trigger(provider)` returns `(triggered, reasons)`, degrading while `UNVALIDATED_AGAINST_LIVE_HOST` is True; `_maybe_auto_merge` forks on a new `ci_provider` param and calls it on the non-github path. The strict-xfail acceptance test is removed atomically with the fork.

**Tech Stack:** Python stdlib, pytest. Test env: `.venv/bin/python -m pytest`.

---

### Task 1: `build_poller` trigger seam

**Files:**

- Modify: `scripts/build_poller.py`
- Test: `tests/orchestrator/test_build_poller.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/orchestrator/test_build_poller.py`)

```python
# --- trigger seam (CCE-123) -------------------------------------------------


def test_resolve_build_trigger_degrades_honestly_while_unvalidated():
    triggered, reasons = build_poller.resolve_build_trigger("circleci")
    assert triggered is False  # no dispatch performed
    assert reasons == ["circleci_trigger_modeled_but_unvalidated"]


def test_resolve_build_trigger_flag_flip_routes_into_trigger_circleci(monkeypatch):
    # Once the honesty gate flips, the fork routes into the unimplemented trigger.
    monkeypatch.setattr(build_poller, "UNVALIDATED_AGAINST_LIVE_HOST", False)
    with pytest.raises(NotImplementedError):
        build_poller.resolve_build_trigger("circleci")


def test_trigger_circleci_is_a_stub():
    with pytest.raises(NotImplementedError):
        build_poller.trigger_circleci(build_poller.FakeCircleCiClient())


def test_trigger_unvalidated_reason_is_fixed_literal():
    _triggered, reasons = build_poller.resolve_build_trigger("circleci")
    assert reasons == [build_poller.TRIGGER_UNVALIDATED_REASON]
    assert "token" not in build_poller.TRIGGER_UNVALIDATED_REASON
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/orchestrator/test_build_poller.py -q`
Expected: FAIL — `AttributeError: module 'build_poller' has no attribute 'resolve_build_trigger'`.

- [ ] **Step 3: Implement** (append to `scripts/build_poller.py`, after `resolve_build_verdict`)

```python
# --- trigger seam (CCE-123) -------------------------------------------------

# Fixed-literal partial reason for the honest trigger degrade. Never interpolates
# a token/response (same discipline as PROVIDER_UNVALIDATED_REASON).
TRIGGER_UNVALIDATED_REASON = "circleci_trigger_modeled_but_unvalidated"


def trigger_circleci(client: Any) -> bool:
    """Real CircleCI v2 pipeline trigger. NOT IMPLEMENTED — no live CircleCI host
    exists to validate the trigger API (CCE-123; mirrors CCE-63 §10). Reached only
    once UNVALIDATED_AGAINST_LIVE_HOST is flipped."""
    raise NotImplementedError("CircleCI trigger unvalidated — see CCE-123")


def resolve_build_trigger(provider: str) -> tuple[bool, list[str]]:
    """Return (triggered, reasons) for a non-github provider's post-merge build
    trigger. While UNVALIDATED_AGAINST_LIVE_HOST is True, degrade honestly: no
    dispatch, a fixed 'modeled but unvalidated' reason. Once flipped, route into
    trigger_circleci (which raises until the real trigger ships). GitHub never
    routes here — it keeps its native gh.workflow_run dispatch in _maybe_auto_merge."""
    if UNVALIDATED_AGAINST_LIVE_HOST:
        return (False, [TRIGGER_UNVALIDATED_REASON])
    client = CircleCiClient()
    trigger_circleci(client)  # raises until the real trigger ships
    return (True, [])
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/orchestrator/test_build_poller.py -q`
Expected: PASS (the pre-existing strict-xfail `test_publish_trigger_is_provider_aware` still XFAILs here — it flips in Task 2).

- [ ] **Step 5: Commit**

```bash
git add scripts/build_poller.py tests/orchestrator/test_build_poller.py
git commit -m "feat(CCE-123): add resolve_build_trigger seam to build_poller

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `_maybe_auto_merge` provider fork + strict-xfail removal

**Files:**

- Modify: `scripts/orchestrator_runner.py` (import, `_maybe_auto_merge` signature + dispatch block, call site ~2048)
- Modify: `tests/orchestrator/test_build_poller.py` (remove the strict-xfail marker — atomic with the fork)
- Test: `tests/orchestrator/test_auto_merge.py`

- [ ] **Step 1: Write the failing tests** — update the `_run` helper and add fork tests in `tests/orchestrator/test_auto_merge.py`

Change the `_run` helper signature + call to thread `ci_provider`:

```python
def _run(
    gh,
    *,
    partial=False,
    fact_warnings=None,
    settings=None,
    build_workflow="docs-agent-pages.yml",
    deadline=None,
    clock=None,
    ci_provider=None,
):
    clock = clock or FakeClock()
    return orun._maybe_auto_merge(
        gh,
        pr_number=7,
        partial=partial,
        fact_warnings=fact_warnings or [],
        merge_settings=settings or _settings(),
        build_workflow=build_workflow,
        deadline=deadline,
        clock=clock,
        sleep=clock.sleep,
        ci_provider=ci_provider,
    )
```

Add (after `test_no_build_workflow_skips_dispatch`):

```python
def test_circleci_provider_skips_dispatch_with_info_reason():
    """CCE-123: a circleci host merges but does NOT fire a GH Actions dispatch;
    it records one info_only pages_dispatch_skipped reason instead."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, reasons = _run(gh, ci_provider="circleci")
    assert outcome["merged"] is True
    assert not [c for c in gh.calls if c[0] == "workflow_run"]
    assert (
        "pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated",
        True,
    ) in reasons


def test_github_provider_still_dispatches():
    """CCE-123 backward-compat: explicit ci_provider=github behaves identically
    to the pre-CCE-123 unconditional dispatch."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, reasons = _run(gh, ci_provider="github")
    assert ("workflow_run", ("docs-agent-pages.yml",)) in gh.calls
    assert ("pages_dispatch_succeeded: docs-agent-pages.yml", True) in reasons
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/orchestrator/test_auto_merge.py -q`
Expected: FAIL — `TypeError: _maybe_auto_merge() got an unexpected keyword argument 'ci_provider'`.

- [ ] **Step 3a: Add the import** — near the other `from <module> import` lines at the top of `scripts/orchestrator_runner.py`

```python
from build_poller import resolve_build_trigger
```

- [ ] **Step 3b: Add the `ci_provider` param** to `_maybe_auto_merge` (in the keyword-only block, e.g. after `build_workflow: str | None,`)

```python
    ci_provider: str | None = None,
```

- [ ] **Step 3c: Fork the dispatch block** — replace the current tail of `_maybe_auto_merge` (the `if build_workflow:` block through `return {"merged": True, "reason": None}, reasons`)

```python
    reasons: list[tuple[str, bool]] = [(f"auto_merge_succeeded: pr={pr_number}", True)]
    provider = ci_provider or "github"
    if provider == "github":
        if build_workflow:
            dispatch = gh.workflow_run(build_workflow)
            if dispatch.ok:
                reasons.append((f"pages_dispatch_succeeded: {build_workflow}", True))
            else:
                reasons.append((f"pages_dispatch_failed: {dispatch.error}", True))
    else:
        # CCE-123: non-github providers degrade honestly — no GH Actions dispatch,
        # one info_only reason. Real trigger stubbed behind UNVALIDATED_AGAINST_LIVE_HOST.
        _triggered, trigger_reasons = resolve_build_trigger(provider)
        for r in trigger_reasons:
            reasons.append((f"pages_dispatch_skipped: {r}", True))
    return {"merged": True, "reason": None}, reasons
```

- [ ] **Step 3d: Thread `ci_provider` at the call site** (`scripts/orchestrator_runner.py`, the `_maybe_auto_merge(...)` call near line 2048) — add:

```python
            ci_provider=config.get("publishing", {}).get("ci_provider"),
```

- [ ] **Step 3e: Remove the strict-xfail** in `tests/orchestrator/test_build_poller.py` — delete the `@pytest.mark.xfail(..., strict=True)` decorator above `test_publish_trigger_is_provider_aware` and refresh its comment:

```python
def test_publish_trigger_is_provider_aware():
    # CCE-123: the post-merge publish TRIGGER (distinct from CCE-63's verify seam)
    # forks on ci_provider inside orchestrator_runner._maybe_auto_merge.
    import inspect

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner

    trigger_src = inspect.getsource(orchestrator_runner._maybe_auto_merge)
    assert "ci_provider" in trigger_src
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/orchestrator/test_auto_merge.py tests/orchestrator/test_build_poller.py -q`
Expected: PASS — new fork tests green; `test_publish_trigger_is_provider_aware` now a normal pass (no xfail).

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_auto_merge.py tests/orchestrator/test_build_poller.py
git commit -m "feat(CCE-123): provider-aware publish trigger in _maybe_auto_merge

github keeps gh.workflow_run; non-github degrades via resolve_build_trigger
with an info_only pages_dispatch_skipped reason. Strict-xfail removed.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Docs — schema description + CLAUDE.md seam note

**Files:**

- Modify: `templates/config.schema.json` (`ci_provider` description)
- Modify: `CLAUDE.md` (CircleCI-seam note)

- [ ] **Step 1: Update the schema description** — in `templates/config.schema.json`, extend the `ci_provider` `description` to note **both** seams now fork:

Append to the existing description string: ` The post-merge trigger (_maybe_auto_merge) also forks on this field (CCE-123): a non-github provider records an info_only pages_dispatch_skipped reason instead of a GH Actions dispatch; the real CircleCI trigger is stubbed.`

- [ ] **Step 2: Update CLAUDE.md** — find the note describing the trigger as a GitHub-only seam deferred to CCE-123 and update it to state the trigger is now provider-aware (honest-degrade), real trigger still stubbed. (Use `grep -n "CCE-123\|GitHub-only seam\|workflow_run" CLAUDE.md` to locate.)

- [ ] **Step 3: Run schema + full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS (schema tests + everything green). If mkdocs site-build tests error with `ModuleNotFoundError: mkdocs`, install docs deps: `.venv/bin/python -m pip install -r requirements-docs.txt` and re-run (pre-existing env gap, not a regression).

- [ ] **Step 4: Commit**

```bash
git add templates/config.schema.json CLAUDE.md
git commit -m "docs(CCE-123): note trigger seam forks on ci_provider

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:** Task 1 → components §4.1; Task 2 → §4.2/4.3/4.4; Task 3 → §4.5. Acceptance criteria 1–4 covered by Tasks 1–2; AC5 by Task 3 Step 3 (full suite); AC6 by `test_github_provider_still_dispatches` + no schema/eligibility change.
- **Type consistency:** `resolve_build_trigger(provider: str) -> tuple[bool, list[str]]` used identically in build_poller and the `_maybe_auto_merge` fork; reason literal `circleci_trigger_modeled_but_unvalidated` identical in impl, tests, and the fork's `pages_dispatch_skipped:` prefix.
- **Coupling guard:** Task 2 removes the strict-xfail in the SAME commit as the fork (Step 3c + 3e) — the suite is green at every commit boundary.

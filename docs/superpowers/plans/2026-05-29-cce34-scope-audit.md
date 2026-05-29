# CCE-34 Scope Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out CCE-34 by adding the missing `actions/upload-pages-artifact` floor entry to the Node-24 guard, with an explicit regression test, and shipping the audit spec as the documentation artifact that records why the rest of CCE-34's scope is refuted or deferred.

**Architecture:** One small modification to `tests/ci/test_workflow_node_runtime.py` (add a dict entry + add one explicit regression test). The audit-design spec at `docs/superpowers/specs/2026-05-29-cce34-scope-audit-design.md` is the documentation artifact this PR also ships.

**Tech Stack:** Python 3, pytest, GitHub Actions YAML.

**Branch:** `chore/CCE-34-scope-audit` (the `chore/` prefix matches the small-scope guard-hardening + closure-doc nature of the change).

---

### Task 1: Add `actions/upload-pages-artifact` floor entry + explicit regression test

**Files:**

- Modify: `tests/ci/test_workflow_node_runtime.py:25-30` (NODE24_FLOOR dict)
- Modify: `tests/ci/test_workflow_node_runtime.py` (append new explicit test below the existing tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/ci/test_workflow_node_runtime.py` (after `test_pages_deploy_workflows_disable_jekyll`):

```python
def test_upload_pages_artifact_in_node24_floor():
    """Regression guard: `actions/upload-pages-artifact` must carry a Node-24 floor.

    v4 of this action shipped Node 20 (deprecated June 2026); v5 is the first
    Node-24 major. The template-validity test (test_workflow_pages_template.py)
    pins the template to @v5, but without this floor entry a host or this repo
    could drift to @v4 on this single action and the runtime guard would
    silently pass — exactly the symmetry gap CCE-34 called out.
    """
    assert NODE24_FLOOR.get("actions/upload-pages-artifact") == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/ci/test_workflow_node_runtime.py::test_upload_pages_artifact_in_node24_floor -v`
Expected: FAIL — `assert None == 5` (the key is not in the dict yet).

- [ ] **Step 3: Add the dict entry**

In `tests/ci/test_workflow_node_runtime.py`, modify `NODE24_FLOOR` so it reads:

```python
NODE24_FLOOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/configure-pages": 6,
    "actions/deploy-pages": 5,
    "actions/upload-pages-artifact": 5,
}
```

- [ ] **Step 4: Run the new test + the existing tests in this file to confirm green**

Run: `python3 -m pytest tests/ci/test_workflow_node_runtime.py -v`
Expected: all three (now four) tests pass. The pre-existing `test_no_workflow_pins_a_node20_action_major` now also covers `upload-pages-artifact` automatically.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest`
Expected: same pass/skip count as `main` (no regressions). Document the count in the eventual commit body.

- [ ] **Step 6: Stage and commit**

Stage only the test file and the spec/plan docs (the plan and spec were already created in this branch's preceding steps).

```bash
git add tests/ci/test_workflow_node_runtime.py \
        docs/superpowers/specs/2026-05-29-cce34-scope-audit-design.md \
        docs/superpowers/plans/2026-05-29-cce34-scope-audit.md
git commit -m "$(cat <<'EOF'
chore(CCE-34): add upload-pages-artifact to NODE24_FLOOR + close audit

Closes the symmetry gap CCE-34 item 2 named: the template-validity test
hard-checks actions/upload-pages-artifact@v5, but the runtime Node-24
guard's NODE24_FLOOR dict was missing the entry, so a host (or this repo)
regressing to @v4 on that single action would pass the runtime check
unnoticed. v4 ships Node 20 (deprecated June 2026); v5 is the first
Node-24 major.

Adds the floor entry and an explicit regression test that asserts the
entry exists with value 5. The pre-existing
test_no_workflow_pins_a_node20_action_major now also covers
upload-pages-artifact automatically.

CCE-34 item 1 (dogfood verify-loop source mismatch) was already shipped
in commit 32182e1; item 3 (template path-trigger breadth) is deferred as
correctness-neutral. Both audit conclusions are recorded in
docs/superpowers/specs/2026-05-29-cce34-scope-audit-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

- **Spec coverage:** The spec calls for (1) the dict entry, (2) an explicit regression test, (3) shipping the audit doc. Task 1 covers all three.
- **Placeholder scan:** No TBD/TODO/etc in the plan. All code blocks are complete.
- **Type consistency:** The dict key is `"actions/upload-pages-artifact"` and value `5` everywhere it appears.

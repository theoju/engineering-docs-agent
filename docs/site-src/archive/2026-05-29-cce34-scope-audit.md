---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CCE-34 Scope Audit — Implementation Plan

**Ticket:** CCE-34  
**Closed by:** PR #80  
**Branch:** `chore/CCE-34-scope-audit`  
**Date:** 2026-05-29

## Goal

Close CCE-34 by adding the missing `actions/upload-pages-artifact` entry to the `NODE24_FLOOR` dictionary in the CI node-runtime test suite, with an explicit regression test. The companion design spec (`archive/2026-05-29-cce34-scope-audit-design.md`) records why the remaining two scope items are refuted or deferred.

## Architecture

One modification to `tests/ci/test_workflow_node_runtime.py`: add a dict entry and one explicit regression test. No production runtime code changes. The audit-design spec ships alongside this plan as the documentation artifact for the closure.

**Tech stack:** Python 3, pytest, GitHub Actions YAML.

---

## Task 1: Add `upload-pages-artifact` floor entry and regression test

### Step 1 — Write the failing test

Append `test_upload_pages_artifact_in_node24_floor` to `tests/ci/test_workflow_node_runtime.py` after the existing `test_pages_deploy_workflows_disable_jekyll` test:

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

### Step 2 — Verify the test fails

```bash
python3 -m pytest tests/ci/test_workflow_node_runtime.py::test_upload_pages_artifact_in_node24_floor -v
```

Expected: `FAIL — assert None == 5`. The key is absent from `NODE24_FLOOR`.

### Step 3 — Add the dict entry

Update `NODE24_FLOOR` in `tests/ci/test_workflow_node_runtime.py:25-30`:

```python
NODE24_FLOOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/configure-pages": 6,
    "actions/deploy-pages": 5,
    "actions/upload-pages-artifact": 5,
}
```

### Step 4 — Confirm green on the full file

```bash
python3 -m pytest tests/ci/test_workflow_node_runtime.py -v
```

All four tests pass. The pre-existing `test_no_workflow_pins_a_node20_action_major` now automatically covers `upload-pages-artifact` as well.

### Step 5 — Run the full suite

```bash
python3 -m pytest
```

Expected: same pass/skip count as `main`. No regressions. Record the count in the commit body.

### Step 6 — Stage and commit

```bash
git add tests/ci/test_workflow_node_runtime.py \
        docs/superpowers/specs/2026-05-29-cce34-scope-audit-design.md \
        docs/superpowers/plans/2026-05-29-cce34-scope-audit.md
git commit -m "chore(CCE-34): add upload-pages-artifact to NODE24_FLOOR + close audit"
```

The commit message body records: the symmetry gap, the v4/v5 Node-20/Node-24 context, the existing test now covering the new entry automatically, and the disposition of items 1 and 3 as already-shipped and deferred respectively.

---

## Self-review checklist

- **Spec coverage:** the spec calls for (1) the dict entry, (2) an explicit regression test, (3) shipping the audit doc. Task 1 covers all three.
- **TDD sequence followed:** failing test written before the dict entry was added.
- **No production code changed:** the modification is test-only.
- **Type consistency:** dict key `"actions/upload-pages-artifact"` and value `5` match everywhere.

## References

- Design spec: `archive/2026-05-29-cce34-scope-audit-design.md`
- Modified file: `tests/ci/test_workflow_node_runtime.py` — `NODE24_FLOOR` dict and `test_upload_pages_artifact_in_node24_floor`
- PR #80: closes CCE-34 umbrella audit
- CCE-32: originating Pages guard hardening work

---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CI Node 24 Floor Guard

GitHub Actions enforces Node 24 on its hosted runners from **2026-06-02**. Any workflow step that uses an action major pinned to Node 20 will hard-fail after that date. The `NODE24_FLOOR` dict in `tests/ci/test_workflow_node_runtime.py` is the single source of truth that prevents this regression.

## What the guard does

The test `test_no_workflow_pins_a_node20_action_major` (line 41) scans every `.yml` and `.yaml` file under `.github/workflows/` plus every `workflow-*.yml` template under `templates/`. For each `uses: actions/<name>@v<major>` line it finds, it checks whether the pinned major meets the floor defined in `NODE24_FLOOR`. If any action falls below the floor, the test fails with a list of violations.

The guard covers workflow templates too. Templates are copied verbatim to host repos during setup, so they must meet the same floor as the repo's own workflows.

## Covered actions and their floors

| Action | Minimum major | First Node-24 release |
|---|---|---|
| `actions/checkout` | v5 | checkout@v5 |
| `actions/setup-python` | v6 | setup-python@v6 |
| `actions/configure-pages` | v6 | configure-pages@v6 |
| `actions/deploy-pages` | v5 | deploy-pages@v5 |
| `actions/upload-pages-artifact` | v5 | upload-pages-artifact@v5 |

`actions/upload-pages-artifact` was added to the dict in PR #80 (CCE-34 audit). Before that fix, a workflow using `upload-pages-artifact@v4` would run Node 20 and the guard would silently pass.

## The regression test

`test_upload_pages_artifact_in_node24_floor` (line 66) is an explicit guard on the guard itself. It asserts that `NODE24_FLOOR.get("actions/upload-pages-artifact") == 5`. If someone removes or downgrades that entry, this test catches the removal before `test_no_workflow_pins_a_node20_action_major` becomes blind to v4 usage again.

This follows the pattern: when a dict entry is the only thing preventing a class of silent regression, write a test that asserts the entry's presence and value, not just the behavior the entry enables.

## Extending the guard

When you add a new `actions/*` step to any workflow or template, check whether the action's latest stable major runs on Node 24. If the action ships a `runs.using: node24` version, add it to `NODE24_FLOOR` in `tests/ci/test_workflow_node_runtime.py:25` with the minimum passing major. Then update your workflow or template to use at least that major.

If the action does not yet publish a Node-24 major, do not add it to `NODE24_FLOOR` — pin the latest available major and open a tracking issue. Adding an entry with a floor that no released major satisfies will cause `test_no_workflow_pins_a_node20_action_major` to flag every existing usage as a violation.

## CCE-34 audit scope

CCE-34 audited three items:

1. **`actions/checkout` and `actions/setup-python` floors** — already present in `NODE24_FLOOR` before the audit (resolved in commit `32182e1`). No further work required.
2. **`actions/upload-pages-artifact` floor** — missing from `NODE24_FLOOR`. Fixed in PR #80 by adding the `v5` entry and the regression test.
3. **Template path-trigger breadth** — flagged as correctness-neutral; deferred with no new issue opened.

The audit is closed. The `NODE24_FLOOR` dict now covers all five actions used across this repo's workflows and templates.

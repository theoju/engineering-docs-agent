---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CCE-34 Scope Audit — Design Spec

**Ticket:** CCE-34  
**Closed by:** PR #80  
**Date:** 2026-05-29

## Background

CCE-34 was opened as a follow-up to CCE-32 (Pages guard hardening) to audit three scope items that were identified but not fully resolved in that work: dogfood verify-loop source reconciliation and CI node-runtime guard completeness. This spec records the final disposition of each item.

## Scope items

### Item 1 — Dogfood verify-loop source reconciliation (shipped before this PR)

The verify-loop's source references were already reconciled in a prior merge. Item 1 is closed with no action required here.

### Item 2 — `upload-pages-artifact` missing from `NODE24_FLOOR` (fixed in PR #80)

The `NODE24_FLOOR` dictionary in `tests/test_workflow_node_runtime.py` enumerated every GitHub Actions action that the CI workflow uses, asserting each must pin to Node 24 or higher. The entry for `actions/upload-pages-artifact` was absent.

The gap meant a future deletion of that action from the workflow would not fail the test suite — the suite would pass while the production workflow silently dropped the action. The missing entry created a symmetry gap, not a correctness defect in the current code.

**Fix:** `actions/upload-pages-artifact` is added to `NODE24_FLOOR` with value `5` (the action's major version). A dedicated regression test, `test_upload_pages_artifact_in_node24_floor`, asserts the entry exists and carries the expected value. No production runtime code changes.

### Item 3 — Deferred (correctness-neutral)

The third scope item was evaluated and determined to be correctness-neutral in the current codebase. It is deferred with no blocking impact on CI or runtime behavior. The deferral is recorded here so a future audit can re-evaluate if the surrounding context changes.

## Decision

All three items are resolved. CCE-34 is marked Done. The only code artifact from this closure is the regression test in `tests/test_workflow_node_runtime.py`; the two audit documents (this spec and the accompanying implementation plan) are archived under `docs/site-src/archive/`.

## Test coverage

| Test | File | Assertion |
|---|---|---|
| `test_upload_pages_artifact_in_node24_floor` | `tests/test_workflow_node_runtime.py` | `NODE24_FLOOR["actions/upload-pages-artifact"] == 5` |

## References

- PR #80: closes CCE-34 umbrella audit
- CCE-32: originating Pages guard hardening work
- `tests/test_workflow_node_runtime.py` — `NODE24_FLOOR` dict and regression test

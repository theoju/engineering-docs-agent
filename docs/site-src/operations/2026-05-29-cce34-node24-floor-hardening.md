---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CCE-34: NODE24_FLOOR Hardening and Audit Closure

**Date:** 2026-05-29  
**PR:** [#80](https://github.com/theoju/engineering-docs-agent/pull/80)  
**Jira:** CCE-34

## What changed

PR #80 closes the CCE-34 umbrella audit by addressing the last actionable scope item from CCE-32's generic deploy capability.

`actions/upload-pages-artifact` was absent from the `NODE24_FLOOR` constraint dict in `tests/ci/test_workflow_node_runtime.py`. The entry is now present with value `5`. A new regression test, `test_upload_pages_artifact_in_node24_floor`, asserts the entry exists — if it is removed in the future, the test fails loudly rather than silently.

Two audit artifacts were also shipped directly in this PR: a design spec at `docs/superpowers/specs/2026-05-29-cce34-scope-audit-design.md` and an implementation plan at `docs/superpowers/plans/2026-05-29-cce34-scope-audit.md`. These record the full audit scope and disposition for each item.

## Audit item disposition

CCE-34 tracked three non-blocking follow-up items from CCE-32.

**Item 1 — source mismatch.** Fixed in a prior commit before this PR. No action required here.

**Item 2 — NODE24_FLOOR symmetry gap.** Fixed in this PR. `upload-pages-artifact` is now in the constraint dict and covered by a dedicated regression test.

**Item 3 — template path-trigger breadth.** Intentionally deferred. A broader CI trigger is conservative, not incorrect. No test or constraint change is needed.

## Why the symmetry gap mattered

`NODE24_FLOOR` defines the minimum Node.js major version required by each workflow action. A missing entry creates a silent gap: the constraint system would not catch a version regression for that action, and — critically — no test would flag the missing entry itself. Adding the entry and a regression test closes both holes at once.

## Files affected

| File | Change |
|------|--------|
| `tests/ci/test_workflow_node_runtime.py` | Added `actions/upload-pages-artifact: 5` to `NODE24_FLOOR`; added `test_upload_pages_artifact_in_node24_floor` |
| `docs/superpowers/specs/2026-05-29-cce34-scope-audit-design.md` | New audit design spec |
| `docs/superpowers/plans/2026-05-29-cce34-scope-audit.md` | New audit implementation plan |

## No breaking changes

This change is additive. Existing tests are unaffected. The new regression test only fails if `upload-pages-artifact` is removed from `NODE24_FLOOR` — which is the behavior you want.

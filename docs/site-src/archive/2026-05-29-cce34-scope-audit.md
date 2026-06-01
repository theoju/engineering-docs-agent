---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CCE-34 Scope Audit — Decision Record (2026-05-29)

CCE-34 was opened as a follow-up to CCE-32 to harden the Pages CI guard and reconcile a reported dogfood verify-loop source mismatch. The audit covered three items. Two are closed; one is explicitly deferred.

## Item 1 — Dogfood verify-loop source mismatch

**Status: refuted (already fixed).**

The reported mismatch between the verify-loop's expected source and the actual deployed artifact was investigated. Commit `32182e1` had already corrected the source reference before CCE-34 was opened. No further action is needed.

## Item 2 — NODE24_FLOOR symmetry gap

**Status: fixed in PR #80.**

The CI Node-24 runtime guard maintains a `NODE24_FLOOR` dict that maps GitHub Actions actions to the minimum major version that ships Node 24. The dict was missing an entry for `actions/upload-pages-artifact`. A host regressing to `@v4` of that action would silently pass the guard: `v4` ships Node 20, which is deprecated as of June 2026; `v5` is the first release on the Node-24 runtime.

PR #80 adds the missing entry and a regression test, `test_upload_pages_artifact_in_node24_floor`, that asserts the floor entry exists. The CI hardening details are in [operations/2026-05-29-node24-floor-upload-pages-artifact.md](../operations/2026-05-29-node24-floor-upload-pages-artifact.md).

## Item 3 — Template `paths:` trigger breadth

**Status: deferred.**

The audit noted that the workflow template's `paths:` trigger is broader than the minimum necessary set. This is correctness-neutral: the trigger fires on changes it does not need to, but never misses changes it should catch. No doc target was assigned. If trigger narrowing becomes relevant for cost or noise reasons, a separate ticket should cover it.

## Outcome

CCE-34 is closed Done. The only actionable residual was Item 2, which shipped in PR #80. Items 1 and 3 required no code change.

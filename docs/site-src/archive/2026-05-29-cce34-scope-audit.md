---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CCE-34 Scope Audit — Closure Record

**Date closed:** 2026-05-29  
**Closed by:** PR #80  
**Parent ticket:** CCE-32 follow-up

CCE-34 tracked three items that surfaced during the CCE-32 review. All three are now resolved or formally deferred.

## Item 1 — Dogfood verify-loop source mismatch

**Status: shipped (pre-PR #80)**

The verify-loop was reading sources from the wrong path in the dogfood configuration. This caused the post-merge publish verification stage to check a stale URL instead of the live published page.

Fixed in commit `32182e1`. No action required in PR #80.

## Item 2 — `actions/upload-pages-artifact` absent from NODE24_FLOOR

**Status: fixed in PR #80**

The CI Node-24 runtime guard (`NODE24_FLOOR`) enforced a minimum action version for several GitHub Actions steps, but `actions/upload-pages-artifact` was missing from the dict. A host that pinned the action at `@v4` (Node 20, deprecated June 2026) would pass the guard silently — the check never fired because there was no floor entry to compare against.

PR #80 adds `actions/upload-pages-artifact` to `NODE24_FLOOR` with a floor value of `5` and ships a dedicated regression test that asserts the entry exists. You can verify the fix at `scripts/ci_node24_guard.py` (search `NODE24_FLOOR`) and the test at `tests/test_ci_node24_guard.py`.

## Item 3 — Template path-trigger breadth

**Status: deferred, no follow-up ticket**

The path triggers in the workflow templates were assessed as correctness-neutral: the broader trigger set does not cause false-negative guard failures or missed deployments. Narrowing them would be a hygiene improvement, not a correctness fix.

No follow-up ticket was opened. If you want to revisit this, scope it as a standalone cleanup; it does not block any current feature work.

## Artifacts

The CCE-34 audit produced two `docs/superpowers` artifacts on this host:

- `docs/superpowers/specs/` — scope-audit spec recording findings for all three items.
- `docs/superpowers/plans/` — corresponding implementation plan, now complete.

Both files were shipped in PR #80 alongside the `NODE24_FLOOR` fix.

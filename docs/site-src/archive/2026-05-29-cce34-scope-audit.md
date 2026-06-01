---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CCE-34 Scope Audit — Decision Record

**Date:** 2026-05-29  
**Ticket:** CCE-34 (umbrella)  
**PR:** [#80](https://github.com/theoju/engineering-docs-agent/pull/80)

## What CCE-34 audited

CCE-34 was an umbrella ticket that audited the `NODE24_FLOOR` runtime guard in `tests/ci/test_workflow_node_runtime.py`. The guard asserts that every GitHub Actions action in the CI workflows specifies a minimum Node 24 version, blocking silent regressions to Node 20 (deprecated June 2026 by the `actions/` ecosystem).

The audit identified three items:

| Item | Description | Outcome |
|------|-------------|---------|
| 1 | Initial `NODE24_FLOOR` entries were incomplete | Resolved in commit `32182e1` before this PR |
| 2 | `actions/upload-pages-artifact` missing from the guard | **Fixed in PR #80** |
| 3 | Template path-trigger breadth (`.github/workflows/` trigger patterns) | Deferred — correctness-neutral, no new issue opened |

## What changed

PR #80 added `actions/upload-pages-artifact` to the `NODE24_FLOOR` dict in `tests/ci/test_workflow_node_runtime.py`. Without this entry, a host or this repo could downgrade that action to v4 — which runs Node 20 — and the CI guard would silently pass.

An explicit regression test was paired with the fix, following the TDD path: failing test first, then implementation.

## Why item 3 was deferred

The template path-trigger breadth issue is correctness-neutral: the existing trigger patterns do not cause incorrect behavior, they are simply broader than necessary. The risk/cost trade-off does not justify a dedicated ticket at this time. No new CCE issue was opened. If a future audit revisits CI trigger hygiene, item 3 is the natural starting point.

## Artifacts

Two supporting documents were shipped in the `docs/superpowers/` tree (superpowers lens):

- **Spec** — records the full scope of CCE-34 and the rationale for each item's disposition.
- **Plan** — captures the TDD steps taken for item 2.

The canonical operational documentation for the guard itself lives at [`operations/ci-node24-floor-guard.md`](../operations/ci-node24-floor-guard.md).

## Deprecation deadline

The `v4 → v5` deprecation for `actions/upload-pages-artifact` (and related `actions/` packages) takes effect June 2026. This fix lands before that deadline. No further action is needed for this item.

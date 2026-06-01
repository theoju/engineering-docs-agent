---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CCE-34 Scope Audit — Design Decision Record

**Date:** 2026-05-29  
**Ticket:** CCE-34  
**PR:** [#80](https://github.com/theoju/engineering-docs-agent/pull/80)

## Background

CCE-34 opened as an audit umbrella following CCE-32. It tracked three items found during a review of the dogfood verify-loop and the CI Node.js runtime guards:

1. Dogfood verify-loop source mismatch
2. `NODE24_FLOOR` gap — `actions/upload-pages-artifact` absent from the pinned floor check
3. Template `paths:` trigger breadth — actionlint not running on every PR

This record documents the audit outcome and the disposition of each item.

## Item 1 — Verify-loop source mismatch (refuted and closed)

The suspected mismatch between the dogfood verify-loop source and the actual deployed site was investigated prior to PR #80. The refutation and fix shipped in an earlier commit. No further action is needed.

## Item 2 — NODE24_FLOOR gap (fixed in PR #80)

The `NODE24_FLOOR` pinning list enforces a Node 24 version floor across all actions that invoke Node.js at runtime. `actions/upload-pages-artifact` was absent from that list, creating an asymmetry: the action ran without the floor check that every peer action carries.

PR #80 adds `actions/upload-pages-artifact` to `NODE24_FLOOR` and updates the CI workflow-node-runtime test to cover the new entry. The guard is now symmetric across all relevant actions.

## Item 3 — Actionlint branch-protection coverage (deferred)

CCE-59 flagged that actionlint must run on every PR for branch-protection compatibility. The audit spec documents this requirement; the fix is deferred to a dedicated ticket. Until CCE-59 lands, actionlint runs on a narrower trigger set than branch protection requires.

## Artifact locations

The full audit spec and implementation plan live under the host-specific superpowers tree:

- `docs/superpowers/specs/` — audit design spec
- `docs/superpowers/plans/` — implementation plan

Those paths are a convention of this host repo, not a plugin requirement. The core lens pages (this record and the companion [Node 24 floor operations note](../operations/2026-05-29-node24-floor-upload-pages-artifact.md)) surface the decisions in the navigable docs site.

## Status

| Item | Disposition |
|------|-------------|
| 1 — Verify-loop source mismatch | Refuted and closed (prior commit) |
| 2 — NODE24_FLOOR gap | Fixed in PR #80 |
| 3 — Actionlint branch-protection | Deferred to CCE-59 |

CCE-34 is closed. CCE-59 carries the remaining open item.

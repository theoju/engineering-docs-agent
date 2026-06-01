---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# Node 24 Floor: Add `actions/upload-pages-artifact` (CCE-34)

**Date:** 2026-05-29  
**Ticket:** CCE-34  
**PR:** [#80](https://github.com/theoju/engineering-docs-agent/pull/80)

## What changed

`actions/upload-pages-artifact` was missing from the `NODE24_FLOOR` pinned version-floor list. Every other Pages-adjacent action was covered; this one was not, creating an asymmetry in Node 24 floor enforcement.

PR #80 adds the entry to `NODE24_FLOOR` and updates the `ci/workflow-node-runtime` test to assert coverage of the new entry.

## Why it matters

The `NODE24_FLOOR` list is the single place where CI enforces a minimum Node.js runtime version across all actions. A gap here means one action can silently run on an older runtime while the rest are pinned. The omission was caught during the CCE-34 scope audit.

## CCE-34 audit scope

The audit covered three items:

1. **Dogfood verify-loop source mismatch** — refuted and resolved in a prior commit before this PR.
2. **`NODE24_FLOOR` gap for `upload-pages-artifact`** — fixed in PR #80 (this change).
3. **Template `paths:` trigger breadth** — deferred. No action required now.

CCE-59 (actionlint must run on every PR for branch-protection compatibility) was identified during the audit and is documented in the accompanying audit spec. It is deferred to a future ticket.

## What you need to do

Nothing. The fix is additive and non-breaking. If you maintain a fork or derivative of this repo's workflow files, add `actions/upload-pages-artifact` to your local `NODE24_FLOOR` equivalent to stay in sync.

## Related

- Audit design decision record: [`archive/2026-05-29-cce34-scope-audit-design.md`](../archive/2026-05-29-cce34-scope-audit-design.md)
- Original Node 24 floor work: CCE-32
- Deferred actionlint item: CCE-59

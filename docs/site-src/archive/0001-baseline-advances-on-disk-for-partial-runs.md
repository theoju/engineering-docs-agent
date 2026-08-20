---
title: "ADR 0001: The Baseline Advances On Disk Even When a Run Is Partial"
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/228
synthesized_into: []
doc_kind: decision
---

# ADR 0001: The Baseline Advances On Disk Even When a Run Is Partial

**Date:** 2026-08-15
**Status:** Accepted. Reaffirms CCE-40 §7 row 4 after it was challenged by CCE-153.

## Context

A nightly run writes its computed advance into the host's `state.json` on its own docs branch. That file only reaches the host's default branch if the docs PR merges. So there are two separate moments where progress could be refused: when the advance is **computed**, or when it is **promoted** by the merge.

CCE-40 chose promotion as the refusal point, and named the on-disk write an _ephemeral advance_ — see the "Ephemeral advance" and "Promotion" entries in the [glossary](../architecture/glossary.md). A run always writes the advance it computed; the merge decides whether that advance becomes the next window's lower bound (the "baseline").

CCE-140 later introduced deferral tracking, and with it a contrary intuition: that a run which still owes pages should not compute an advance past the PRs that owe them. Its clamp was scoped narrowly, to runs cut short by a time budget, so the two ideas didn't collide in practice — a content-validator block still advanced on disk per CCE-40, and the merge gate refused to promote it.

CCE-153 read that narrow scoping as an oversight and proposed widening the clamp to cover any run with deferrals, not just time-truncated ones. That change failed `tests/orchestrator/test_state_advancement_invariant.py`, which pins CCE-40's rules explicitly. The failure was the design speaking, not stale coverage, so the change was reverted.

What made the underlying question live wasn't the failing test — it was a real incident on a host repository. Three consecutive runs dropped pages to `citation_exists` validator blocks, advanced on disk exactly as designed, and were then **merged by a human**. The merge gate that's supposed to refuse promotion is a decision made inside the agent process; it has no standing with the forge. Nothing stopped a person from clicking merge, and promotion happened anyway. Pages were stranded — not because the advance was computed, but because it was promoted without the deferred pages ever landing.

## Decision

Keep CCE-40's model. A run computes and writes its advance regardless of whether it is partial. Refusal to make that advance real belongs at promotion, not at computation.

Close the actual gap — an advisory-only promotion gate — by making that gate **enforceable rather than advisory**, so that a partial run without a cursor-backed advance cannot be promoted by any actor, automated or human. (That enforcement work is tracked separately under CCE-153's retargeted scope and is not part of this record.)

Two alternatives were considered and explicitly rejected:

- **Clamping the advance for any deferral.** This moves the refusal to the wrong moment, contradicts a decision CCE-40 made deliberately, and would leave two mechanisms expressing one invariant with no clear authority between them.
- **Re-running an old window to recover stranded pages.** Page filenames aren't derived deterministically from their sources, so re-deriving a window emits new pages beside the old ones instead of replacing them. One attempt at this produced six duplicate topics. A window is not a retry mechanism; deferral is.

## Consequences

The on-disk advance stays a proposal, and its meaning stays single: "this is where the run got to." Reading `state.json` on a docs branch tells you nothing about whether the work behind it was accepted — by design.

Every failure class is now covered by one mechanism at one moment, so a new kind of failure needs no new clamp; it needs only to be marked as making the run partial.

The cost is that correctness now depends on a gate outside the agent process. That gate must be configured on each host, and a host that omits it is unprotected in exactly the way that prompted this record. The agent cannot verify its own promotion gate, so adoption belongs in host setup, and setup wants a check that flags a host as missing it.

If you're reading the advance code for the first time, you'll likely see a partial run write a full-window advance and reasonably suspect a bug. That reaction is exactly why this record exists — the behavior is intentional, and the safety property it depends on lives at merge time, not in this code path.

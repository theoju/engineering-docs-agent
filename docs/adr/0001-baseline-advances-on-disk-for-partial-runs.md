# 1. The baseline advances on disk even when the run is partial

Date: 2026-08-15

## Status

Accepted. Reaffirms CCE-40 §7 row 4 after it was challenged by CCE-153.

## Context

A run writes its computed advance into the host's `state.json` on its own docs
branch. That file reaches the host's default branch only if the docs PR merges.
So there are two distinct moments where progress could be refused: when the
advance is **computed**, or when it is **promoted** by the merge.

CCE-40 chose promotion, and named the on-disk write an _ephemeral advance_. A
run always writes the advance it computed; the merge decides whether that
becomes the next window's lower bound.

CCE-140 later introduced deferral tracking, and with it a contrary intuition —
that a run which owes pages should not compute an advance past the PRs that owe
them. Its clamp was scoped to runs cut short by a time budget, so the two ideas
did not collide in practice: a content-validator block still advanced on disk,
per CCE-40, and the merge gate refused to promote it.

CCE-153 read that scoping as an oversight and proposed widening the clamp to any
run with deferrals. Doing so failed
`tests/orchestrator/test_state_advancement_invariant.py`, which pins CCE-40's
rules explicitly. The failure was the design speaking, not stale coverage.

What made the question live was a real incident on a host repository. Three
consecutive runs dropped pages to validator blocks, advanced on disk as
designed, and were then **merged by a human**. The merge gate is a decision made
inside the agent process; it has no standing with the forge. Nothing stopped a
person from clicking merge, and promotion happened anyway. Pages were stranded —
not because the advance was computed, but because it was promoted.

## Decision

Keep CCE-40's model. A run computes and writes its advance regardless of whether
it is partial. Refusal to make that advance real belongs at promotion.

Close the gap by making the promotion gate **enforceable rather than advisory**,
so that a partial run without a cursor-backed advance cannot be promoted by any
actor — automated or human.

We explicitly reject two alternatives:

- **Clamping the advance for any deferral.** It moves the refusal to the wrong
  moment, contradicts a decision made deliberately in CCE-40, and would leave
  two mechanisms expressing one invariant with no clear authority between them.
- **Re-running an old window to recover stranded pages.** Page filenames are not
  derived deterministically from their sources, so re-deriving a window emits
  new pages beside the old ones rather than replacing them. One attempt produced
  six duplicate topics. A window is not a retry mechanism; deferral is.

## Consequences

The on-disk advance stays a proposal, and its meaning stays single: "this is
where the run got to." Reading `state.json` on a docs branch continues to tell
you nothing about whether the work was accepted — by design.

Every failure class is covered by one mechanism at one moment, so a new kind of
failure needs no new clamp; it needs only to mark the run partial.

The cost is that correctness now depends on a gate outside the agent process.
That gate must be configured on each host, and a host that omits it is
unprotected in exactly the way that prompted this record. The agent cannot
verify its own promotion gate, so adoption belongs in host setup and wants a
check that a host is missing it.

Anyone reading the advance code will see a partial run write a full-window
advance and reasonably suspect a bug. That reaction is why this record exists.

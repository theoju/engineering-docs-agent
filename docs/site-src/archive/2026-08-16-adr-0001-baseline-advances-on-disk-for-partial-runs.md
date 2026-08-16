---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/228
synthesized_into: []
doc_kind: decision
---

# ADR 0001: The Baseline Advances on Disk Even When the Run Is Partial

**Date:** 2026-08-15
**Status:** Accepted. Reaffirms CCE-40 §7 row 4 after it was challenged by CCE-153.

## Context

A run writes its computed advance into the host's `state.json`, on its own docs
branch. That file reaches the host's default branch only if the docs PR merges.
So there are two distinct moments where progress could be refused: when the
advance is **computed**, and when it is **promoted** by the merge.

CCE-40 chose promotion. It named the on-disk write an _ephemeral advance_ — see
the glossary entry in `CONTEXT.md` — and the rule is unconditional: a run always
writes the advance it computed, whether or not the run is partial. The merge
decides whether that advance becomes the next window's lower bound. Read
`state.json` on a docs branch and you learn only where the run got to, never
whether the work was accepted.

CCE-140 later added deferral tracking, and with it a contrary intuition: a run
that owes pages, you might expect, should not compute an advance past the PRs
that owe them. Its clamp was scoped narrowly, to runs cut short by the time
budget, so the two ideas didn't collide in practice. A content-validator block
still advanced on disk, per CCE-40, and the merge gate refused to promote it.

CCE-153 read that narrow scoping as an oversight and proposed widening the
clamp to any run with deferrals. Implementing it failed
`tests/orchestrator/test_state_advancement_invariant.py`, which pins CCE-40's
rules explicitly. That failure was the design speaking, not stale coverage.

What made the question live was a real incident on a host repository. Three
consecutive runs dropped pages to validator blocks, advanced on disk as
designed — and were then **merged by a human**. The promotion gate lives inside
the agent process; it has no standing with the forge. Nothing stopped a person
from clicking merge, and promotion happened anyway. Pages were stranded — not
because the advance was computed, but because it was promoted.

## Decision

Keep CCE-40's model. A run computes and writes its advance regardless of
whether it is partial. Refusal to make that advance real belongs at promotion,
not at computation.

Close the gap that the incident exposed by making the promotion gate
**enforceable rather than advisory**, so that a partial run without a
cursor-backed advance cannot be promoted by any actor — automated or human.
That enforceability work is tracked separately, retargeted under CCE-153.

Two alternatives were considered and rejected:

- **Clamping the advance for any deferral.** This moves the refusal to the
  wrong moment — computation instead of promotion — contradicts a decision
  made deliberately in CCE-40, and would leave two mechanisms expressing one
  invariant with no clear authority between them.
- **Re-running an old window to recover stranded pages.** Page filenames
  aren't derived deterministically from their sources, so re-deriving a window
  emits new pages beside the old ones instead of replacing them. One attempt
  produced six duplicate topics. A window is not a retry mechanism; deferral
  is.

## Consequences

The on-disk advance stays a proposal, and its meaning stays single: "this is
where the run got to." Reading `state.json` on a docs branch still tells you
nothing about whether the work was accepted — by design.

Every failure class is covered by one mechanism at one moment, so a new kind
of failure needs no new clamp — it needs only to mark the run partial.

The cost is that correctness now depends on a gate outside the agent process.
That gate must be configured on each host, and a host that omits it is
unprotected in exactly the way that prompted this record. The agent can't
verify its own promotion gate; adoption belongs in host setup, which wants a
check for a host that's missing it.

If you read the advance code cold, you'll see a partial run write a
full-window advance and reasonably suspect a bug. That reaction is why this
record exists.

## Related terms

For the vocabulary this decision depends on — baseline, cursor, window head,
ephemeral advance, promotion, deferral, owed page, held back, partial run,
truncation — see the domain glossary in `CONTEXT.md`. The baseline/cursor
distinction in particular is easy to blur: the cursor is the moving position
during a run; the baseline is the recorded value it produces, and only merge
turns that recorded value into fact.

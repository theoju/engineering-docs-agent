---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/228
synthesized_into: []
doc_kind: decision
---

# ADR: the baseline advance is ephemeral until promotion

## Status

Accepted. Reaffirms the CCE-40 design after it was challenged by CCE-153.

## Context

A run writes its computed advance into the host's `state.json` on its own docs
branch. That file reaches the host's default branch only if the docs PR
merges. So there are two distinct moments where progress could be refused:
when the advance is **computed**, or when it is **promoted** by the merge.

CCE-40 chose promotion, and named the on-disk write an *ephemeral advance*. A
run always writes the advance it computed; the merge decides whether that
becomes the next window's lower bound. This is why reading `state.json` on a
docs branch tells you nothing about whether the work was accepted — that's by
design, not an oversight.

CCE-140 later introduced deferral tracking, and with it a contrary intuition:
that a run which still owes pages should not compute an advance past the PRs
that owe them. Its clamp was scoped to runs cut short by a time budget, so the
two ideas didn't collide in practice — a content-validator block still
advanced on disk, per CCE-40, and the merge gate refused to promote it.

CCE-153 read that scoping as an oversight and proposed widening the clamp to
any run with deferrals. Implementing it broke
`tests/orchestrator/test_state_advancement_invariant.py` and
`tests/orchestrator/test_cursor_backed_merge.py`, both of which pin the CCE-40
rules explicitly. The failure was the design speaking, not stale coverage.

What made the question live was a real incident on a host repository: three
consecutive runs dropped pages to validator blocks, advanced on disk exactly
as designed, and were then **merged by a human**. The merge gate is a decision
made inside the agent process — it has no standing with the forge. Nothing
stopped a person from clicking merge, and promotion happened anyway. Pages
were stranded not because the advance was computed, but because it was
promoted.

## Decision

Keep the CCE-40 model. A run computes and writes its advance regardless of
whether it is partial. Refusal to make that advance real belongs at
promotion, not at computation.

Close the actual gap by making the promotion gate enforceable rather than
advisory, so that a partial run without a cursor-backed advance cannot be
promoted by any actor — automated or human. That retargeting is the scope of
the reopened CCE-153 work; this record exists to fix the reasoning in place
first, before the enforcement mechanism lands.

### Rejected alternatives

- **Clamping the advance for any deferral.** This moves the refusal to the
  wrong moment, contradicts a decision made deliberately in CCE-40, and would
  leave two mechanisms expressing one invariant with no clear authority
  between them.
- **Re-running an old window to recover stranded pages.** Page filenames
  aren't derived deterministically from their sources, so re-deriving a window
  emits new pages beside the old ones rather than replacing them — one attempt
  produced six duplicate topics. A window is not a retry mechanism; deferral
  is.

## Consequences

The on-disk advance stays a proposal, and its meaning stays single: "this is
where the run got to." If you're reading advance code and see a partial run
write a full-window advance, that's expected — not a bug. This record exists
because that reaction is the natural one to have.

Every failure class is covered by one mechanism at one moment, so a new kind
of failure needs no new clamp — it needs only to mark the run partial.

The cost is that correctness now depends on a gate outside the agent process.
You must configure that gate on each host; a host that omits it is
unprotected in exactly the way that prompted this record. The agent cannot
verify its own promotion gate, so adoption belongs in host setup, and setup
wants a check that flags a host missing it.

## Related vocabulary

The terms this record depends on — window, baseline, cursor, promotion,
ephemeral advance, admission gate, deferral, owed page, forgiveness, held
back, partial run, truncation, batch, block, drift — are glossary entries,
not decisions. If this lens doesn't yet carry an architecture glossary page
defining them, add one under `architecture/`; keep definitions there and keep
decisions here, so a future ADR doesn't have to re-derive what "baseline"
means before it can argue about it.

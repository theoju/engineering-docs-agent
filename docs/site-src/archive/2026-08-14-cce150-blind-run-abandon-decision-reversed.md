---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/223
synthesized_into: []
doc_kind: decision
---

# CCE-150: blind-run abandon decision, reversed nine minutes later

This page is a decision-history record only. It does not describe current
system behavior. For CCE-144's actual current behavior, see the CCE-144
bullet in `CLAUDE.md` and
`docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`.

## What happened

An operator instructed a session to abandon the unmerged
`feat/CCE-144-blind-run-detection` branch and archive its design as a dead
end. PR #223 (CCE-150) recorded that abandon decision: it edited
`docs/superpowers/plans/2026-08-13-cce144-blind-run-detection.md` and
`docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md` to
stamp the CCE-144 design as archived, on the premise that the branch was
never pushed and its commits were unreachable from `main`.

That premise was wrong. Nine minutes after PR #223 merged, PR #224 merged
the same implementation to `main`, reversing the abandon decision in
practice. The two plan and spec files PR #223 had just stamped "archived"
became, nine minutes later, accurate descriptions of what actually shipped.

PR #223's body was subsequently heavily annotated to flag itself as
superseded and factually false as a description of current state. It was
kept merged rather than reverted, specifically to preserve the record of
the reversed decision — and the commit-provenance caveat below — not to
document what shipped. Do not treat this page, or PR #223, as a source for
architecture or operations claims about blind-run detection.

## Timeline

1. Operator instructs abandonment of the unmerged CCE-144 branch.
2. PR #223 merges: plan and spec stamped "archived," on the premise the
   branch was never pushed.
3. Nine minutes later, PR #224 merges: the same CCE-144 implementation
   lands on `main`, reversing step 2's premise and its conclusion.
4. PR #223's body is annotated post-merge to warn readers off its own
   original claims.

## Provenance caveat: squash-merge and the 20-commit history

PR #224 squash-merged the CCE-144 implementation. The resulting tree at
`5021f11` matches `main`'s tree at `087bfbc` across all seven changed
files — the content landed intact. But the original 20-commit history
behind that squash is not reachable from `main`'s commit graph. It is
preserved at `refs/pull/224/head` and under the tag `cce144-preserved-5021f11`,
should anyone need the original commit-by-commit record rather than the
squashed result.

## Why this page exists at all

The abandon decision in PR #223 was real, and it was reversed. Neither the
plan file nor the spec file's current banners fully capture *why* an
operator believed abandonment was correct at the time, or how quickly that
belief was overturned. This page keeps that record without duplicating
CCE-144's actual behavior, which lives in `CLAUDE.md` and the spec file
linked above.

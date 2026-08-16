---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/223
synthesized_into: []
doc_kind: decision
---

# CCE-150: The CCE-144 Abandon-Then-Reverse (2026-08-14)

> **This page documents a decision that did not stick.** It is a forensic
> record of what the operator decided and then undecided nine minutes later —
> not a description of current orchestrator behavior. For the actual CCE-144
> blind-run-detection behavior (the exit code, `state_io.add_partial`'s
> `blind` flag, the blind gate in `_maybe_auto_merge`), read PR #224, which is
> what actually shipped and is reachable from `main`. Nothing below should be
> cited as current system behavior.

## What happened

`feat/CCE-144-blind-run-detection` sat unpushed for a time — 20 commits, head
`5021f11`. The operator's working assumption was that the branch had been
abandoned: nobody had pushed it, so deleting it would lose the only copy of
the CCE-144 incident analysis and the blind-vs-degraded classification it
worked out. Acting on that assumption, PR #223 archived the spec and plan —
`docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md` and
`docs/superpowers/plans/2026-08-13-cce144-blind-run-detection.md` — onto
`main`, stamping both with "design approved — NOT IMPLEMENTED" banners. The
intent was to preserve the design as a historical record while being explicit
that none of it had landed.

Nine minutes after PR #223 merged, that premise turned out to be false. The
branch *had* been pushed, at `5021f11`, and PR #224 merged the same
implementation — squash-merged as `087bfbc`, with a tree byte-identical to
`5021f11` — straight to `main`. PR #224 then removed the "NOT IMPLEMENTED"
banners PR #223 had just added, since the design was no longer just approved:
it was live.

PR #223's own body was subsequently rewritten with a large "SUPERSEDED BY
#224 — DO NOT DOCUMENT ANYTHING BELOW AS CURRENT STATE" notice, flagging
every original factual claim in that PR as false. Both the spec and the plan
now carry their own superseding notes pointing back at PR #224 and marking
CCE-150 (this ticket) obsolete.

## Why this page exists at all

Neither file PR #223 touched lives under `docs/site-src/` — they're under
`docs/superpowers/specs/` and `docs/superpowers/plans/`, this host's internal
spec/plan convention, outside the `core` lens's `docs.lens_paths`. So PR #223
made no direct edit to any published docs page, and there is no "current
state" page for it to have corrected. This entry exists only to preserve
institutional memory of the reversed decision, per the incident-logging
convention CLAUDE.md already follows for CCE-101, CCE-109, CCE-127, and the
rest of the archive.

## The squash-merge history caveat

Because PR #224 squash-merged, `5021f11` is **not** an ancestor of `main`.
The pre-squash commit history from `feat/CCE-144-blind-run-detection` survives
in exactly two places: `refs/pull/224/head` on the remote, and the local tag
`cce144-preserved-5021f11`. Anyone who needs the original per-commit history
of the CCE-144 implementation — rather than the single squashed commit
`087bfbc` now on `main` — has to go to one of those two refs. Neither is
discoverable by `git log main` alone.

## Lesson

The failure mode here wasn't the archival itself — writing down "design
approved, not implemented" against a branch that genuinely was abandoned
would have been correct. The failure mode was archiving on an unverified
premise ("nobody pushed this") that turned out to be checkable and wrong. The
nine-minute gap between PR #223 and PR #224 means the two PRs' factual claims
are mutually exclusive, and only one of them — #224 — describes what's
actually on `main` today. When a decision record and the state it describes
can diverge this fast, treat "the branch is gone" as a claim to verify against
the remote (`git branch -r`, `gh pr list --state all`), not as a
default assumption before deleting or archiving anything.

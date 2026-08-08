---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/199
synthesized_into: []
doc_kind: decision
---

# CCE-130: Stale Branch Archive and Prune (2026-08-08)

**PR:** #199

PR #199 archives 35 stale `docs-agent/*` branches — spanning `docs-agent/2026-06-11T08` through the tail end of the CCE-127 outage window on 2026-08-08 — into `.engineering-docs-agent/stale-prs-archive/`, then deletes the corresponding remote branches. It's a one-time maintenance sweep: only `.engineering-docs-agent/stale-prs-archive/` JSON archives changed, no runtime code. After the sweep, `docs-agent/2026-08-08T08` (PR #198) is the only live docs-agent branch.

Each archived branch gets a JSON file (`pr-<number>.json`) in the existing CCE-90 archive format — `body`, `createdAt`, `files`, `headRefName`, `headRefOid`, `number`, `statusCheckRollup`, `title` — the same shape used for every prior stale-PR archive in that directory (see, for example, `pr-138.json` and `pr-197.json`).

## Why the branches piled up

D2 auto-close (CCE-89) closes a superseded docs-agent PR, but branch deletion only happens on the merge path — `gh pr merge --delete-branch`. A superseded PR never merges, so every superseded nightly leaves its head branch behind as a permanent ref. Under normal operation this self-limits, because most nightlies do merge and prune. It stopped self-limiting during the CCE-127 App-token outage: 15 consecutive nightlies failed between 2026-07-23 and 2026-08-07, so nothing merged and nothing swept, and the branch count grew to 36 before this cleanup.

None of the 35 archived branches were ever merged into `main` — every one belonged to a PR that D2 auto-closed as superseded by a later, fresher run.

## Relationship to CCE-90

This is the branch-level analogue of the 2026-05-30→06-01 stale-PR pileup that CCE-89's D1/D2 fixed at the PR-object level, and of the local-branch cleanup `scripts/prune_merged_branches.py` (CCE-90) already handles for merged branches on an operator's machine. CCE-90's script only prunes branches that merged and went `[gone]`; it has no reach into remote branches left behind by a PR that was closed, not merged. That surface was left open until this sweep.

No runbook or script currently automates this remote-branch class of cleanup — this PR is a manual sweep, not a new capability. If the pattern recurs, formalizing it as a recurring runbook step (alongside `docs/runbooks/release-and-rollback.md`) is the natural next move.

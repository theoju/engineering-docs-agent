---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/139
synthesized_into: []
doc_kind: decision
---

# CCE-99: `/ship` Post-Merge Prune Hook — Design

**Ticket:** CCE-99  
**Date:** 2026-06-10  
**Status:** Shipped (user-global; non-durable)

## Problem

Every `gh pr merge --delete-branch` call removes the remote branch but leaves the local ref tracking it. The branch lingers in `git branch -vv` output as `[gone]`, and the workspace branch list accumulates stale entries over time. The 2026-06-04 CCE-90 sweep recovered 13 such refs. The existing `scripts/prune_merged_branches.py` helper required a manual `--apply` invocation after every batch of merges — an easy step to skip.

## Decision

Add a PostToolUse hook to the user-global `/ship` skill that fires automatically after each successful `gh pr merge` call. The hook prunes local `[gone]` branches without a separate manual step.

The hook lives at `~/.claude/` (user-global, non-durable). It is not scaffolded onto host repos.

## Hook Design

**Trigger:** PostToolUse on any tool call whose output indicates a `gh pr merge` invocation completed successfully.

**SHA verification:** Before force-deleting a squash-merged branch, the hook reads the branch's tip commit and compares the full 40-character hash against the merged PR's `headRefOid` returned by `gh pr view`. A mismatch aborts deletion for that branch and logs the conflict. This prevents accidental deletion of branches that were amended locally after the merge.

**Idempotence:** The hook re-reads `git branch -vv` on each invocation. Branches already deleted are absent from the output; no double-delete path exists.

**Journal output:** Each pruned branch name and its former SHA are appended to the ship journal. To restore a branch after pruning: `git branch <name> <sha>`.

## Accepted Residual Risks

**Non-durable.** The hook lives in `~/.claude/` and does not survive a machine reset or a fresh Claude install without re-deployment. This is a known limitation of user-global hooks; no automated restore path exists.

**SHA verification is cooperation-dependent.** The hook verifies against the PR API response. If the PR record is unavailable — network outage, deleted repository — the hook skips deletion for safety rather than proceeding blindly.

**Worktree orphans are out of scope.** The PostToolUse hook targets `[gone]` merged branches only. `worktree-*` orphan refs left by the Workflow tool's `isolation: 'worktree'` mode require a separate `scripts/prune_merged_branches.py --apply` invocation. CCE-100 tracks upstream worktree-harness cleanup independently.

## Relationship to CCE-90

CCE-90 (2026-06-04) identified the accumulation problem and shipped `scripts/prune_merged_branches.py` as a manual remediation tool. CCE-99 closes the loop at the `/ship` skill level by eliminating the manual step for the common case. The CLAUDE.md bullet on `prune_merged_branches.py` cross-references both tickets and should link to the operations page once it exists.

## References

- PR #139 — design record (this document) and full implementation plan
- `scripts/prune_merged_branches.py` — manual fallback helper; dry-run by default, `--apply` to delete
- `docs/site-src/operations/post-merge-prune-hook.md` — operations page covering trigger pattern, SHA verification logic, journal format, and restore procedure
- CCE-90 — initial stale-branch sweep; 13 refs recovered 2026-06-04
- CCE-100 — upstream worktree-harness cleanup (separate ticket, separate scope)

---
title: "Decision: CCE-99 — Post-Merge Branch Pruning Hook"
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/139
synthesized_into: []
doc_kind: decision
---

# Decision: CCE-99 — Post-Merge Branch Pruning Hook

**Date:** 2026-06-10  
**Tickets:** CCE-99 (Done), CCE-90 (root cause sweep)  
**PR:** #139

## Problem

After `gh pr merge --delete-branch`, the remote tracking ref disappears but the local branch lingers as `[gone]`. Left unchecked, these refs accumulate. The 2026-06-04 CCE-90 sweep recovered 13 such stale entries requiring a manual `scripts/prune_merged_branches.py --apply` run.

A manual helper is the floor — it doesn't prevent accumulation between sweeps. The gap closes only if pruning happens automatically at the point of merge.

## Decision

Ship a user-global `PostToolUse` hook (`~/.claude/`) that fires after any Bash tool call whose command matches `gh pr merge`. The hook worker prunes the local branch that was just merged, without operator intervention.

The hook lives in `~/.claude/` and is not tracked in this repo. Only the design artifacts — a 132-line spec and a 771-line implementation plan — land here under `docs/superpowers/`.

## Hook behavior

The worker resolves the merged PR's `headRefOid` via `gh pr view --json headRefOid` and verifies the local branch tip against the full 40-character SHA before force-deleting. Short-SHA or absent-SHA mismatches cause the worker to skip with an advisory log line rather than error.

For squash-merged branches, `git branch -d` refuses because the squash commit doesn't appear in `main`'s graph — the worker uses `git branch -D` only after the `headRefOid` check passes, providing the safety guarantee that `-d` would normally supply.

Every deletion is journaled as `branch@shortsha` so you can recover any accidentally pruned branch with:

```bash
git branch <branch-name> <shortsha>
```

The hook is idempotent: if the branch was already deleted (e.g., by a prior manual prune), it exits cleanly.

## Alternatives considered

**Extend the `/ship` skill instead.** The skill runs only for this repo's own merges. A user-global `PostToolUse` hook fires for any `gh pr merge` call in any repo — a single install covers the problem everywhere.

**Rely solely on `scripts/prune_merged_branches.py`.** The helper requires operator memory — run it after every merge batch, not just when you notice the branch list growing. The hook removes the reliance on memory entirely.

## Test coverage

The ship test suite reached 147 passed / 0 failed. The CCE-99 addition contributed 36 new assertions covering the hook worker, the `PostToolUse` trigger registration, the journal path, and the advisory (skip) paths for SHA mismatch and already-absent branches.

## Operator notes

The implementation is live in `~/.claude/` and active for any Claude Code session on the machine where it was installed. If you need to disable the hook temporarily, remove or rename `~/.claude/settings.json`'s `postToolUse` entry for the `Bash(gh pr merge*)` pattern.

The in-repo manual floor remains `scripts/prune_merged_branches.py --apply`. Run it if you are on a machine without the hook installed or after importing a branch list from another workspace.

## References

- `scripts/prune_merged_branches.py` — manual sweep helper (CCE-90)
- `docs/superpowers/specs/` — CCE-99 hook spec (132 lines)
- `docs/superpowers/plans/` — CCE-99 implementation plan (771 lines)
- CLAUDE.md plugin conventions: `Run scripts/prune_merged_branches.py --apply after every batch of gh pr merge calls in a session`

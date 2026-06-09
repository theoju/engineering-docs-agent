---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/115
synthesized_into: []
---

# Pruning Merged Branches

After merging PRs with `gh pr merge --delete-branch`, the remote branch is deleted but your local ref lingers as `[gone]`. The Workflow tool's `isolation: 'worktree'` mode adds a second category: `worktree-*` orphan refs that accumulate in the background. Left alone, these compound into a workspace where `git branch` returns dozens of stale entries.

`scripts/prune_merged_branches.py` is a dry-run-by-default helper that clears both categories. Run it after every batch of `gh pr merge` calls in a session.

## Branch buckets

The script operates on two distinct buckets.

**`[gone]` branches** are local branches whose upstream tracking ref no longer exists on origin. This is the normal residue of `gh pr merge --delete-branch`. The script safe-skips any `[gone]` branch that has unmerged commits — the typical pattern when you amended locally without pushing — and reports them so you can review before forcing.

**`worktree-*` orphan refs** are scratch branches created by the Workflow tool's worktree isolation mode. These are throwaway by design; the script force-deletes them without a safety hold.

## CLI modes

**Dry run (default)** — lists what would be deleted, writes nothing:

```bash
python3 scripts/prune_merged_branches.py
```

**`--apply`** — deletes safe-merged `[gone]` branches and all `worktree-*` orphans:

```bash
python3 scripts/prune_merged_branches.py --apply
```

**`--force-unmerged`** — additionally force-deletes `[gone]` branches with unmerged tips. Use this only after reviewing the dry-run skip list:

```bash
python3 scripts/prune_merged_branches.py --apply --force-unmerged
```

## Hard exclusions

The script never touches `main`, `master`, `develop`, or the currently checked-out branch, regardless of flags. These are hard-coded guards, not configurable.

## Recommended workflow

Run dry-run first, scan the output, then `--apply`:

```bash
python3 scripts/prune_merged_branches.py
# review output
python3 scripts/prune_merged_branches.py --apply
```

If the dry run lists `[gone]` branches in the skip-list (unmerged commits), inspect them with `git log <branch>` before deciding whether to add `--force-unmerged`.

## Background

The 2026-06-04 sweep recovered 13 stale local refs: 5 `[gone]` branches and 9 `worktree-*` orphans that had accumulated over the engineering-docs-agent PR workflow (CCE-90). The helper ships as the in-repo floor while upstream prevention is tracked separately: CCE-99 covers wiring this into the `/ship` post-merge hook, and CCE-100 covers upstream worktree-harness cleanup in the Workflow tool itself.

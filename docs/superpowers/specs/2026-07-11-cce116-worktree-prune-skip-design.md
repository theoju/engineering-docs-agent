# CCE-116: prune skips branches checked out in a linked worktree — design

**Date:** 2026-07-11
**Ticket:** [CCE-116](https://designitright.atlassian.net/browse/CCE-116) (child of CCE-90)
**Status:** approved
**Fix surface:** two — (a) in-repo `scripts/prune_merged_branches.py` (the manual floor; ships via the plugin, CI-deployable), and (b) user-global `~/.claude/skills/ship/lib/prune-merged-branches.sh` (the CCE-99 post-merge hook; edited in place, verified by the ship test harness). Both carry the identical gap; the spec lives in the repo for tracking.

## Problem

A `[gone]` local branch that is **checked out in another git worktree** cannot be deleted — `git branch -d` and even `git branch -D` refuse ("cannot delete branch '…' checked out at '…'"). Both pruners only recognize the branch checked out in the _current_ worktree, so a branch checked out elsewhere falls through to a delete attempt that fails:

- **Shell hook** (`prune-merged-branches.sh:39,48`): `CURRENT=$(git branch --show-current)` sees only the current worktree; a linked-worktree branch reaches the `git branch -D` attempt (`:79`) and lands at `:82` as the misleading `delete-failed`. This is the CCE-116 report.
- **Python floor** (`prune_merged_branches.py:120,126`): `find_pruneable_branches` excludes only `name == current`; a linked-worktree `[gone]` branch is classified `reason="gone"`, then `prune_branch`'s `git branch -d` refuses → reported `skipped_unmerged` with the advice _"re-run with --force-unmerged"_ — advice that then also **fails** (`-D` refuses a checked-out branch too). Doubly misleading.

## Root cause

`git branch --show-current` / `symbolic-ref HEAD` report only the invoking worktree's HEAD. The authoritative list of every branch checked out across all worktrees is `git worktree list --porcelain`, which emits one `branch refs/heads/<name>` line per worktree that has a branch checked out (or `detached`).

## Decision (brainstormed 2026-07-11, grounded by the CCE-116 scout)

Detect **every** branch checked out in **any** worktree via `git worktree list --porcelain`, and treat a candidate that is checked out elsewhere as a clean skip — never a delete attempt.

- **Shell hook:** skip with reason `checked-out (worktree)` (parallels the existing `checked-out` reason for the current worktree), inserted after the protected-name check and before the `git rev-parse` / delete path.
- **Python floor:** extend the existing "current branch" exclusion in `find_pruneable_branches` to "checked out in any worktree." Silent exclusion, consistent with how `current`/`protected` are already dropped — strictly better than the misleading `skipped_unmerged` advice. A new helper `_worktree_checked_out_branches(repo_root) -> set[str]` parses the porcelain output.

The current-worktree branch is itself in the porcelain set, so the new check subsumes the old one; both scripts keep the narrower current-branch handling for clarity and let the worktree check catch the _other_-worktree case.

### `git worktree list --porcelain` parse

Per worktree block: `worktree <path>` / `HEAD <sha>` / (`branch refs/heads/<name>` | `detached`). Collect the `<name>` from every `branch refs/heads/` line into a set. A detached worktree contributes nothing (correct — no branch is "held").

## Architecture

**Python floor** — `scripts/prune_merged_branches.py`:

```python
def _worktree_checked_out_branches(repo_root: Path) -> set[str]:
    """Branch names checked out in ANY worktree (incl. the current one).
    git branch -d/-D refuse to delete such a branch, so the pruner must
    exclude them rather than misreport a delete failure. (CCE-116)"""
    r = _run(["git", "worktree", "list", "--porcelain"], repo_root)
    if r.returncode != 0:
        return set()
    return {
        line[len("branch refs/heads/"):].strip()
        for line in r.stdout.splitlines()
        if line.startswith("branch refs/heads/")
    }
```

In `find_pruneable_branches`, after `if name == current: continue`:

```python
        if name in checked_out_elsewhere:   # computed once before the loop
            continue                        # checked out in a linked worktree (CCE-116)
```

**Shell hook** — `~/.claude/skills/ship/lib/prune-merged-branches.sh`: build a newline-sentinel-bounded `WORKTREE_BRANCHES` string before the loop (bash 3.2 safe, no arrays under `set -u`); after the `protected` case, skip with `checked-out (worktree)` when the candidate is in that set and is not `$CURRENT`.

## Degradation

| Condition                              | Behavior                                            |
| -------------------------------------- | --------------------------------------------------- |
| No linked worktrees                    | Set is just the current branch → no behavior change |
| `git worktree list` fails / old git    | Empty set → falls back to today's behavior (safe)   |
| Detached-HEAD worktree                 | Contributes no branch → correct                     |
| Branch checked out in current worktree | Already handled by the existing `current` check     |

## Testing (TDD)

**Python (pytest, `tests/gh/test_prune_merged_branches.py`):**

1. RED→GREEN: a `[gone]` branch checked out in a linked worktree (`git worktree add <path> <branch>`) is **excluded** from `find_pruneable_branches` (before: included as `gone`; after: absent). Mirrors `test_find_pruneable_never_includes_current_branch`.
2. Regression: a `[gone]` branch checked out in **no** worktree is still pruneable (existing tests stay green).

**Shell (`~/.claude/skills/ship/tests/prune-merged-branches.test.sh`):** 3. A candidate `[gone]` branch checked out in a linked worktree → reported `skipped <branch> (checked-out (worktree))`, branch survives, exit 0. Mirrors the existing "checked-out → skipped" case with a `git worktree add` fixture.

Full `python3 -m pytest` green; `~/.claude/skills/ship/tests/run.sh` green.

## Acceptance criteria (mapped to ticket)

1. A `[gone]` branch checked out in another worktree is **skipped** by the post-merge hook with a clear "checked-out (worktree)" reason — never reported `delete-failed`. _(AC 1)_
2. The in-repo Python floor excludes the same branch instead of misreporting `skipped_unmerged`. _(AC 2, thoroughness)_
3. No regression: normal `[gone]` branches (not in any worktree) still prune; existing suites green. _(AC 3)_

## Out of scope

- `worktree-*` orphan-ref cleanup (already handled by the Python floor's `worktree_orphan` bucket; different concern).
- Deleting the worktree itself — the pruner only manages branch refs; a live worktree is the operator's to remove.

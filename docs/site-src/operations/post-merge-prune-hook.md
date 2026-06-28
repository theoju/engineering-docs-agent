---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/139
synthesized_into: []
---

# Post-Merge Branch Prune Hook

The CCE-99 PostToolUse hook fires automatically after every `gh pr merge` call inside the `/ship` skill and deletes the local branch that was just squash-merged. Without it, local branches linger as `[gone]` against origin after `gh pr merge --delete-branch` removes the remote ref, and they accumulate until someone runs `scripts/prune_merged_branches.py --apply` by hand. The 2026-06-04 CCE-90 sweep recovered 13 such stale refs.

## Scope

The hook is **user-global and non-durable** — it lives in `~/.claude/` and is not scaffolded onto host repos. If you reinstall or switch machines, you must redeploy it manually. The design record and acceptance criteria are in `docs/superpowers/specs/2026-06-10-cce99-ship-post-merge-prune-design.md`; the full implementation plan is in `docs/superpowers/plans/2026-06-10-cce99-post-merge-prune.md`.

## Trigger

The hook is a Claude Code `PostToolUse` hook scoped to the `Bash` tool. It fires after every bash invocation, but gates on:

1. The command matching `gh pr merge`.
2. The exit code being `0` (merge succeeded).

It does nothing and exits cleanly on any other tool use or failed merge.

## SHA verification

Squash merges rewrite history: the merged commit SHA is not the same as your local branch tip. The hook calls:

```bash
gh pr view <PR_NUMBER> --json headRefOid --jq '.headRefOid'
```

It extracts the 40-character `headRefOid` from the PR record and verifies your local branch tip matches before calling `git branch -D`. If the SHAs do not match, the hook aborts with a warning and leaves the branch untouched.

This guard prevents accidental deletion of a branch you amended locally after pushing — the common case where you pushed a fixup commit that the PR does not reflect.

## Idempotency

If the local branch has already been deleted (e.g., you ran `scripts/prune_merged_branches.py --apply` before the hook fired), `git branch -D` exits non-zero and the hook suppresses that error. It does not re-delete or raise.

## Journal output

The hook appends a one-line entry to the ship journal after a successful deletion:

```
[prune] deleted <branch-name> (<sha>) after merge of PR #<number>
```

The journal path follows the same convention as the rest of the `/ship` skill. No entry is written for skipped or aborted runs.

## Manual restore

If the hook deleted a branch you still needed, restore it from the SHA:

```bash
git branch <branch-name> <40-char-sha>
```

The SHA is in the journal entry and in the `gh pr view` output for the merged PR. Git retains the object in the reflog until the next `git gc`, so you have time.

## Relationship to `prune_merged_branches.py`

The hook covers the common `/ship` path (one merge, immediate cleanup). `scripts/prune_merged_branches.py --apply` remains the manual fallback for:

- Worktree-harness orphan refs (`worktree-*`) that the PostToolUse hook does not see.
- Sessions where the hook was not installed or failed silently.
- Bulk recovery (the CCE-90 pattern).

See the CLAUDE.md plugin convention bullet for the full `--force-unmerged` and safe-skip behavior of the script. The hook and the script are complementary, not redundant.

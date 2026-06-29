---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/139
synthesized_into: []
---

# Post-merge branch prune (CCE-99)

After `gh pr merge` runs in any Claude session, local feature branches linger as `[gone]` refs. Left alone, they accumulate: the 2026-06-04 sweep recovered 13 stale refs; the 2026-06-10 sweep recovered 7 more.

CCE-99 closes the loop by attaching an automatic prune to `gh pr merge` itself via a global PostToolUse hook. You no longer need to run `scripts/prune_merged_branches.py --apply` manually after each session.

## Design

The hook is **not a `/ship` stage**. All 7 branches from the 2026-06-10 sweep came from merges performed outside `/ship`. The trigger attaches to the `gh pr merge` command itself, so it fires in every Claude session, every repo.

Three pieces compose the feature:

| Piece   | Path |
| ------- | ---- |
| Trigger | `~/.claude/hooks/post-merge-prune.sh` |
| Worker  | `~/.claude/skills/ship/lib/prune-merged-branches.sh` |
| Tests   | `~/.claude/skills/ship/tests/prune-merged-branches.test.sh` |

The trigger reads the PostToolUse stdin JSON, extracts `.tool_input.command`, and exits immediately unless the command contains `gh pr merge`. When it matches, the trigger changes to the hook-reported `.cwd` and execs the worker, passing the original command through `--trigger-cmd`.

The registration in `~/.claude/settings.json`:

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "bash ~/.claude/hooks/post-merge-prune.sh",
      "timeout": 60
    }
  ]
}
```

The 60-second timeout bounds the worst case: one `git fetch` plus one `gh` call per stale branch.

## How the worker runs

The worker (`prune-merged-branches.sh`) always exits 0 — a prune failure must never block the session loop.

Sequence per invocation:

1. Not inside a git repo → silent exit 0.
2. `git fetch --prune` fails (offline) → one report line, then exit 0.
3. Enumerate `[gone]` branches via `git for-each-ref --format='%(refname:short) %(upstream:track)'`. No candidates → silent exit 0; no journal entry.
4. Per candidate branch:
   - **Checked out** → skip with reason `checked-out`.
   - **Protected name** (`main`, `master`, `develop`) → skip with reason `protected`.
   - **`git branch -d` succeeds** → deleted (merge-commit case).
   - **`-d` refused** → squash-merge candidate. Verify with `gh pr list --head <branch> --state merged --json headRefOid`. If any returned `headRefOid` exactly equals `git rev-parse <branch>` (full 40-character compare — never a prefix), run `git branch -D`. Otherwise skip with reason `unverified: tip not on a merged PR`.
   - **`gh` missing or the API call fails** → skip with reason `unverified: gh unavailable`.
5. If the triggering command contained `gh pr merge` but not `--delete-branch`, print an advisory suggesting `--delete-branch` for remote hygiene.
6. Print a compact report to stdout (one line per deleted or skipped branch). PostToolUse stdout surfaces in the session.
7. If anything was deleted or skipped, append one entry to the ship journal.

The full-SHA requirement prevents the force-delete from misfiring. The 2026-06-10 manual sweep's guard initially failed closed on a prefix comparison — the worker uses strict 40-character equality.

## Journal

When the sweep deleted or skipped at least one branch, it appends one JSONL line to `${CLAUDE_PLUGIN_DATA:-$HOME/.claude}/ship/journal.jsonl`:

```json
{
  "ts": "2026-06-10T14:23:01Z",
  "outcome": "pruned",
  "repo": "engineering-docs-agent",
  "deleted": ["feat/CCE-99-ship-post-merge-prune@a3f1bc20"],
  "skipped": [],
  "duration_ms": 1840
}
```

Query pruned entries across all runs:

```bash
jq 'select(.outcome == "pruned")' ~/.claude/ship/journal.jsonl
```

`pruned` is a third outcome shape alongside `shipped` and `halted`.

## Degradation matrix

| Condition | Behavior |
| --------- | -------- |
| Not a git repo | Silent exit 0 |
| `git fetch` fails (offline) | One report line, exit 0 |
| `gh` missing | `-d` safe pass still runs; squash-merged branches skip with reason |
| `gh` API error / rate limit | Affected branch skips with reason |
| Detached HEAD | No checked-out branch name; sweep proceeds normally |
| `jq` missing in trigger | Trigger exits 0 (no-op) |
| Branch deleted by concurrent session | Delete fails → skip-and-report |

## Rollback

Remove the `PostToolUse` entry for `bash ~/.claude/hooks/post-merge-prune.sh` from `~/.claude/settings.json`. A backup was written at `~/.claude/settings.json.pre-cce99-backup` when the entry was registered. Both hook scripts are inert without the registration.

## Recovering a pruned branch

The worker logs a short SHA with every deletion, e.g. `post-merge-prune: deleted feat/my-branch@a3f1bc20`.

Restore using that SHA:

```bash
git branch feat/my-branch a3f1bc20
```

If you missed the session output, query the journal:

```bash
jq 'select(.outcome == "pruned") | .deleted[]' ~/.claude/ship/journal.jsonl
```

Then use the full or short SHA from `.deleted[]` to recreate the branch.

## Implementation scope

The implementation is user-global and non-durable — it lives in `~/.claude/` and is not delivered via this plugin's install path. The in-repo files (`docs/superpowers/specs/2026-06-10-cce99-ship-post-merge-prune-design.md` and `docs/superpowers/plans/2026-06-10-cce99-post-merge-prune.md`) are design artifacts only.

`scripts/prune_merged_branches.py` (CCE-90) remains the manual in-repo floor for batch cleanups and handles `worktree-*` orphan refs that the hook does not touch.

**Reference:** CCE-99, child of CCE-90. PR #139.

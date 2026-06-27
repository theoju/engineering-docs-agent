# CCE-99: post-merge local branch prune — design

**Date:** 2026-06-10
**Ticket:** [CCE-99](https://designitright.atlassian.net/browse/CCE-99) (child of CCE-90)
**Status:** approved
**Fix surface:** user-global (`~/.claude/`) — the spec lives in this repo for tracking; the implementation does not ship via this repo's plugin.

## Problem

Merged feature branches linger locally (and accumulate) because nothing prunes after `gh pr merge`. The 2026-06-04 sweep recovered 13 stale refs; the 2026-06-10 sweep recovered 7 more. CCE-90 shipped the in-repo floor (`scripts/prune_merged_branches.py`), but it only helps when an operator remembers to run it, and only in this repo.

The original CCE-99 framing ("/ship stage 8") is misfit: `/ship` ends at PR creation (Stage 6) and never merges. All 7 of the 2026-06-10 stale branches came from merges performed _outside_ `/ship`. The fix therefore attaches to the merge itself, not to `/ship`'s stage chain.

## Decisions (brainstormed 2026-06-10)

| Question            | Decision                                                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Trigger surface     | Global PostToolUse hook on Bash commands containing `gh pr merge` — fires in every Claude session, every repo. Not `/ship`-gated.                       |
| Squash-merge safety | SHA-verified force-delete: `git branch -D` only when a MERGED PR's `headRefOid` exactly equals the local tip. Everything else safe-skips with a reason. |
| Sweep scope         | Full sweep of all `[gone]` branches per trigger, not just the merged PR's branch.                                                                       |
| Remote deletes      | Never. Local-only; remote hygiene stays with `gh pr merge --delete-branch`.                                                                             |
| Journal             | Append a `pruned` entry to the existing ship journal when the sweep did anything.                                                                       |

## Architecture

Three pieces, following the ship skill's existing two-layer hook pattern (`ship-guardrails.sh` → `lib/validate-git-cmd.sh`):

1. **Worker** — `~/.claude/skills/ship/lib/prune-merged-branches.sh`. All logic. Generic across any repo. Always exits 0.
2. **Trigger** — `~/.claude/hooks/post-merge-prune.sh`. Registered in `~/.claude/settings.json` as `PostToolUse` with matcher `Bash`. Reads the hook stdin JSON; exits 0 immediately unless `.tool_input.command` contains `gh pr merge`; otherwise changes to the hook-reported `.cwd` and execs the worker, passing the original command line through (for the `--delete-branch` advisory). Unlike `ship-guardrails.sh`, it is **not** gated on `/tmp/.ship-active` — covering non-/ship sessions is the point.
3. **Docs** — new spoke `~/.claude/skills/ship/spokes/post-merge-prune.md` documenting the contract and journal schema; one pointer line added to `push-pr.md`'s "Optional: wait-for-green-then-merge" section. No `/ship` stage changes.

A false-positive trigger (the substring `gh pr merge` inside an echoed string or compound command) is acceptable: the worker is self-verifying and idempotent, so the worst case is a few wasted seconds. The worker does not need the merge command's exit code for the same reason — a sweep only deletes branches it can prove merged.

## Worker contract

Invocation: `prune-merged-branches.sh [--trigger-cmd "<original command>"]`, run with cwd inside the target repo.

Sequence:

1. `git rev-parse --git-dir` fails → exit 0 silently (not a repo).
2. `git fetch --prune` (failure → exit 0 with one report line; network may be down).
3. Enumerate local branches whose upstream is gone (`git for-each-ref` + `%(upstream:track)` == `[gone]`).
4. No candidates → exit 0 silently. No journal entry.
5. Per candidate branch:
   - Checked-out branch → skip, reason `checked-out`.
   - Name in `main`/`master`/`develop` → skip, reason `protected` (defense in depth; these should never be `[gone]`).
   - `git branch -d` succeeds → deleted (merge-commit case).
   - `-d` refuses → verify: `gh pr list --head <branch> --state merged --json headRefOid` (in-repo, so `gh` resolves the right remote). Any returned `headRefOid` equals `git rev-parse <branch>` — full 40-character SHA equality, never a prefix compare (the 2026-06-10 manual sweep's guard initially failed closed on exactly that mismatch) → `git branch -D`, deleted (squash-merge case). No match → skip, reason `unverified: tip not on a merged PR`.
   - `gh` missing or the API call fails → skip, reason `unverified: gh unavailable`.
6. If `--trigger-cmd` was passed and it contains `gh pr merge` but not `--delete-branch`, print an advisory: `tip: 'gh pr merge --delete-branch' also removes the remote branch`. String check only; no API call.
7. Print a compact report (one line per deleted/skipped branch) to stdout — PostToolUse hook stdout surfaces in the session.
8. Journal: if at least one branch was deleted or skipped, append one JSONL line to `${CLAUDE_PLUGIN_DATA:-$HOME/.claude}/ship/journal.jsonl`:

   ```json
   {
     "ts": "<UTC ISO>",
     "outcome": "pruned",
     "repo": "<basename of toplevel>",
     "deleted": ["<branch>@<short-sha>"],
     "skipped": [{ "branch": "<branch>", "reason": "<reason>" }],
     "duration_ms": 2300
   }
   ```

   A third entry shape alongside `shipped` and `halted`, queryable the same way (`jq 'select(.outcome == "pruned")'`).

Hard rules: never `git push`. Never delete the checked-out branch. Never exit non-zero. `set -u`, no `set -e` (per-step error handling instead).

## Registration

One entry appended to the `PostToolUse` array in `~/.claude/settings.json`:

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

The 60s timeout bounds the worst case (fetch + one `gh` call per stale branch). Rollback = remove this entry; the two scripts are inert without it.

## Degradation matrix

| Condition                            | Behavior                                                           |
| ------------------------------------ | ------------------------------------------------------------------ |
| Not a git repo                       | Silent exit 0                                                      |
| `git fetch` fails (offline)          | One report line, exit 0                                            |
| `gh` missing                         | `-d` safe pass still runs; squash-merged branches skip with reason |
| `gh` API error / rate limit          | Affected branch skips with reason                                  |
| Detached HEAD                        | No checked-out branch name; sweep proceeds normally                |
| Branch deleted by concurrent session | Delete fails → skip-and-report                                     |
| `jq`/`python3` missing in trigger    | Trigger exits 0 (no-op)                                            |

## Testing

`~/.claude/skills/ship/tests/prune-merged-branches.test.sh`, registered with the existing `tests/run.sh` runner, using its `assert_eq`/`assert_exit` helpers. Fixtures: temp git repos with a `file://` bare remote; a PATH-shim `gh` stub returning canned JSON.

Cases:

1. Merge-commit branch (tip reachable from main), remote deleted → pruned via `-d`.
2. Squash-merged branch, `gh` stub returns matching `headRefOid` → pruned via `-D`.
3. Squash-merged branch, stub returns a different SHA → skipped, reason reported.
4. Squash-merged branch, no `gh` on PATH → skipped, reason `gh unavailable`.
5. Candidate branch is checked out → skipped.
6. No `[gone]` branches → silent, no journal entry.
7. Not a git repo → silent exit 0.
8. Trigger script: non-merge Bash command JSON → no-op (worker not invoked).
9. Trigger script: merge command JSON → worker invoked in the JSON's `cwd`.
10. Journal line shape: valid JSON, `outcome == "pruned"`, deleted/skipped arrays populated.

## Acceptance criteria (mapped to ticket)

1. After an operator (or auto-merge chain) runs `gh pr merge` in any Claude session, the local feature branch is deleted automatically — squash merges included, via SHA verification. _(Ticket AC 1, broadened from "/ship + merge" to "any session".)_
2. No regressions on `/ship`'s existing stages: the chain is untouched; changes are additive (hook + spoke + one doc pointer). The existing ship test suite still passes. _(Ticket AC 2.)_
3. The sweep is documented in the journal as `pruned` entries. _(Ticket AC 3, adapted from "stage entry" to the hook framing.)_

## Sequencing constraint

The repo-side PR for this spec carries `CCE-99` in its title, so merging it auto-transitions the ticket to Done (`jira-transition.yml`). Land the user-global implementation and verify it against a real merge **before** merging that PR.

## Out of scope

- Remote branch deletion (stays with `gh pr merge --delete-branch`).
- `worktree-*` orphan cleanup (CCE-100, upstream/runtime).
- Changes to `scripts/prune_merged_branches.py` (CCE-90, shipped; remains the manual in-repo floor and handles the worktree bucket).
- Merges performed in a human terminal outside Claude sessions (a `gh` shell wrapper was considered and rejected as invasive; revisit only if stale branches keep appearing from that path).

---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/139
synthesized_into: []
doc_kind: decision
---

# CCE-99: post-merge local branch prune hook

Merged feature branches were lingering locally after `gh pr merge` because nothing pruned them. The 2026-06-04 sweep recovered 13 stale `[gone]` refs; a follow-up sweep on 2026-06-10 recovered 7 more. CCE-90 had already shipped an in-repo floor (`scripts/prune_merged_branches.py`), but that only helps when an operator remembers to run it, and only inside this repo.

CCE-99 was originally framed as a `/ship` stage 8 addition. That framing turned out to be wrong: `/ship` ends at PR creation and never merges, and all 7 of the 2026-06-10 stale branches came from merges performed outside `/ship`. The fix attaches to the merge itself, not to `/ship`'s stage chain.

## Decision

A global `PostToolUse` hook on `Bash` commands fires whenever a command contains `gh pr merge` — in every Claude session, in every repo, `/ship` or not. It delegates to a worker that sweeps all local branches whose upstream shows `[gone]`, not just the branch from the triggering merge.

Deletion is two-tier:

- If `git branch -d` succeeds (the branch's history is reachable from the current tip — the merge-commit case), that's the delete.
- If `-d` refuses (the squash-merge case, where the branch tip is never reachable from `main`), the worker force-deletes only after verifying the branch's tip SHA against `gh pr list --head <branch> --state merged --json headRefOid` — a full 40-character equality check, never a prefix compare. The 2026-06-10 manual sweep's guard had failed closed on exactly that mismatch, which is why the spec calls out the full-SHA requirement explicitly.

Remote branch deletion is out of scope — that stays with `gh pr merge --delete-branch`. The hook is local-only and never runs `git push`.

## Where the code lives

The fix surface is a user-global skill edit, not a change to this repo: `~/.claude/skills/ship/lib/prune-merged-branches.sh` (the worker), `~/.claude/hooks/post-merge-prune.sh` (the trigger, registered in `~/.claude/settings.json` as a `PostToolUse` entry), and a new spoke doc, `~/.claude/skills/ship/spokes/post-merge-prune.md`, plus one pointer paragraph added to `push-pr.md`. None of that is committed to this repo's tree.

Because the implementation is non-durable and out-of-repo, CCE-99 exists to give it a durable, reviewable design record here — the spec (`docs/superpowers/specs/2026-06-10-cce99-ship-post-merge-prune-design.md`) and implementation plan (`docs/superpowers/plans/2026-06-10-cce99-post-merge-prune.md`) are committed even though the code they describe is not. The same split applies to CCE-100 (the other CCE-90 child, covering `worktree-*` orphan cleanup).

## Degradation

The worker always exits 0 — it runs as a hook, so a prune failure must never block the session loop:

| Condition | Behavior |
|---|---|
| Not a git repo | Silent exit 0 |
| `git fetch --prune` fails (offline) | One report line, exit 0 |
| `gh` missing | `-d` pass still runs; squash-merged branches skip with a reason |
| `gh` API error or rate limit | Affected branch skips with a reason |
| Branch is checked out | Skipped, reason `checked-out` |
| Branch name is `main`/`master`/`develop` | Skipped, reason `protected` (defense in depth) |

A false-positive trigger — the substring `gh pr merge` inside an echoed string or compound command — is treated as acceptable rather than filtered out further: the worker is self-verifying and idempotent, so the worst case is a few wasted seconds, not an incorrect delete.

## Journal

When a sweep deletes or skips at least one branch, the worker appends one JSONL line to `${CLAUDE_PLUGIN_DATA:-$HOME/.claude}/ship/journal.jsonl` — a third entry shape (`outcome: "pruned"`) alongside the existing `shipped` and `halted` shapes, queryable the same way: `jq 'select(.outcome == "pruned")'`.

## Sequencing

The repo-side PR for the spec and plan carries `CCE-99` in its title, so merging it auto-transitions the Jira ticket to Done via `jira-transition.yml`. The plan's sequencing constraint required landing and live-firing the user-global implementation first — merging the tracking PR itself is the verification step, since the hook only loads at session start and would fire on that very merge.

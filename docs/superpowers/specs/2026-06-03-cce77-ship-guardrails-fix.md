# CCE-77 — Narrow the `/ship` guardrails `-f` token check to git-history-rewriting operations

**Ticket:** CCE-77
**Status:** Draft (awaiting user review)
**Priority:** Low
**Related:** CCE-75 polish run, PR #98 (merged 2026-06-01 22:34:28Z, commit `11eed62`)

## Scope clarification (read first)

The fix does **not** live in this repo. The plugin source ships agent contracts and the orchestrator runner; the `/ship` skill is a personal skill installed in `~/.claude/skills/ship/` on the operator's machine. The spec is filed here because the regression surfaced during a CCE work cycle and you reach for this repo's spec archive when you triage `/ship` papercuts.

Targets (both outside any git repo):

- Hook entry: `~/.claude/hooks/ship-guardrails.sh` — 14-line shim that delegates to the validator. **Not modified.**
- Validator: `~/.claude/skills/ship/lib/validate-git-cmd.sh` — the `-f` token check is at line 40 (the surrounding block spans roughly lines 30-44).

Spec is authored against `~/.claude/skills/ship/lib/validate-git-cmd.sh:40`. The shim stays as-is.

## Problem

The `/ship` PreToolUse guardrails hook blocks any Bash command containing a whitespace-bounded `-f` token, on the assumption that `-f` means `git push --force`. In practice many legitimate shell commands use `-f` as a non-destructive flag and get falsely blocked mid-ship:

- `rm -f <known-temp-file>` — `-f` means "ignore nonexistent" (idempotent cleanup)
- `find <path> -f` — `-f` is a follow-symlinks flag in some BSD `find` variants
- `grep -f patterns.txt` — `-f` reads patterns from a file
- `tar -xzf archive.tar.gz` — `f` is inside a bundled flag set (not actually caught today, but illustrates the ambiguity)
- `gh` and other CLI tools using `-f` as a force/format/file flag

The regression surfaced during the CCE-75 polish `/ship` run for PR #98. The cleanup step `rm -f /tmp/.ship-active /tmp/ship-state-1512165.json` was blocked even though `rm -f` cannot affect git history. Workaround was trivial — split the cleanup into two Bash calls — but it is a recurring papercut on otherwise-clean ship runs.

## Current behavior

`~/.claude/skills/ship/lib/validate-git-cmd.sh:40` does a whitespace-bounded token check:

```bash
if [[ " $CMD " == *" -f "* ]]; then
  block "-f"
fi
```

This matches `-f` as a standalone token regardless of which command word it modifies. The long-form flag checks elsewhere in the validator (`--no-verify`, `--amend`, `--force`, `--force-with-lease`) are correctly scoped to git operations and stay as-is.

## Goal

`-f` blocks only when it is an argument to a git operation that can rewrite history or overwrite a remote. Every other `-f` use — `rm`, `find`, `grep`, `gh`, `tar`, `cp`, `mv`, `ln`, `mkdir`, `chmod`, `chown`, `unzip`, and so on — flows through. The existing long-form checks survive verbatim.

## Non-goals

- Loosening the long-form checks. `--force`, `--force-with-lease`, `--amend`, `--no-verify` stay as block conditions, regression-guarded.
- A general-purpose shell parser. The validator runs on every Bash PreToolUse and must stay fast and dependency-free. A regex with explicit git command words is enough.
- Touching the hook shim at `~/.claude/hooks/ship-guardrails.sh`. The shim only forwards `$CMD` to the validator; no logic change is needed there.

## Design

### Path chosen: git-aware regex

Replace the bare token check with a regex that requires `-f` to follow a `git <subcommand>` prefix on the same command segment:

```bash
# Block -f only on git operations that can rewrite history or overwrite remote
if [[ "$CMD" =~ (^|[\;\&\|[:space:]])git[[:space:]]+(push|commit|checkout|reset|clean|branch|rebase)[^|;&]*[[:space:]]-f([[:space:]]|$) ]]; then
  block "-f (on git $cmd)"
fi
```

The match anchors on `git <subcommand>` after a segment boundary (start of line, `;`, `&`, `|`, or whitespace). The `[^|;&]*` between the subcommand and `-f` keeps the match inside a single command segment, so a pipeline like `git status | rm -f /tmp/x` does not false-trip.

Subcommands covered: `push`, `commit`, `checkout`, `reset`, `clean`, `branch`, `rebase`. Each can rewrite history, force-overwrite a remote, or destroy untracked state when given `-f`.

### Alternative considered: leading-command allowlist

Maintain an allowlist of safe commands (`rm`, `find`, `grep`, `gh`, `tar`, `cp`, `mv`, `ln`, `mkdir`, `chmod`, `chown`, `unzip`) and skip the `-f` check when the leading command word is in the allowlist.

Rejected because:

- It enumerates the world's safe commands instead of the small set of dangerous ones. New CLIs that use `-f` (and there are many) keep tripping until the allowlist catches up.
- A command like `cd /tmp && rm -f x` would need either segment-aware parsing (which the chosen design already does) or a second rule, doubling the surface.
- The git-aware regex is the inversion that the validator's other checks already use for long-form flags — it keeps the file internally consistent.

## Acceptance criteria

1. `rm -f <path>` does **not** block inside `/ship`.
2. `find . -name foo -f` does **not** block inside `/ship`.
3. `git push -f origin main` **does** block inside `/ship`.
4. `git push --force origin main` **does** block (existing long-form check, regression-guarded).
5. `git push --force-with-lease` **does** block (existing check).
6. `git commit --amend` **does** block (existing check).
7. `git commit --no-verify` **does** block (existing check).
8. A new unit/integration test covers each of the 7 cases above.
9. The hook shim at `~/.claude/hooks/ship-guardrails.sh` is unchanged.

## Test plan

The validator lives outside any git repo, so tests run as a standalone shell harness invoking `validate-git-cmd.sh` with `$CMD` set per case and asserting on exit code and stderr.

New cases in the validator's existing test file (or a new one if none exists yet):

- `test_rm_dash_f_passes` — `CMD="rm -f /tmp/foo"` → exit 0.
- `test_find_dash_f_passes` — `CMD="find . -name foo -f"` → exit 0.
- `test_grep_dash_f_passes` — `CMD="grep -f patterns.txt input"` → exit 0.
- `test_gh_dash_f_passes` — `CMD="gh pr create -f"` → exit 0.
- `test_git_push_dash_f_blocks` — `CMD="git push -f origin main"` → exit non-zero, stderr mentions `-f (on git push)`.
- `test_git_push_long_force_blocks` — `CMD="git push --force origin main"` → exit non-zero (regression guard).
- `test_git_push_force_with_lease_blocks` — `CMD="git push --force-with-lease"` → exit non-zero (regression guard).
- `test_git_commit_amend_blocks` — `CMD="git commit --amend"` → exit non-zero (regression guard).
- `test_git_commit_no_verify_blocks` — `CMD="git commit --no-verify"` → exit non-zero (regression guard).
- `test_pipeline_isolates_segments` — `CMD="git status | rm -f /tmp/x"` → exit 0 (the `-f` belongs to `rm`, not git).
- `test_chained_git_push_dash_f_blocks` — `CMD="cd /tmp && git push -f origin main"` → exit non-zero (the segment boundary still hands `-f` to git).

## Behavior matrix

| Command                              | Existing behavior  | Behavior after CCE-77        |
| ------------------------------------ | ------------------ | ---------------------------- |
| `rm -f /tmp/foo`                     | block (false trip) | pass                         |
| `find . -name foo -f`                | block (false trip) | pass                         |
| `grep -f patterns.txt`               | block (false trip) | pass                         |
| `gh pr create -f`                    | block (false trip) | pass                         |
| `git push -f origin main`            | block (correct)    | block (correct, narrowed)    |
| `git push --force origin main`       | block (long-form)  | block (long-form, unchanged) |
| `git push --force-with-lease`        | block (long-form)  | block (long-form, unchanged) |
| `git commit --amend`                 | block (long-form)  | block (long-form, unchanged) |
| `git commit --no-verify`             | block (long-form)  | block (long-form, unchanged) |
| `git status \| rm -f /tmp/x`         | block (false trip) | pass                         |
| `cd /tmp && git push -f origin main` | block (correct)    | block (correct)              |

## Files changed

- `~/.claude/skills/ship/lib/validate-git-cmd.sh` — replace the bare `-f` token check at line 40 with the git-aware regex; surrounding block (lines 30-44) stays in place.
- `~/.claude/skills/ship/tests/` (path depends on existing layout) — add the 11 cases above, or extend the existing validator test file.

No changes to:

- `~/.claude/hooks/ship-guardrails.sh` (14-line shim).
- The long-form flag checks elsewhere in `validate-git-cmd.sh`.
- This repo (`engineering-docs-agent`). The spec is archived here for cross-referencing during future CCE work.

## Risk

- **Regression on legitimate force-push blocks**: mitigated by the explicit regression-guard cases in the test plan (`--force`, `--force-with-lease`, `--amend`, `--no-verify`).
- **Subcommand list drifts behind git**: the chosen subcommands (`push`, `commit`, `checkout`, `reset`, `clean`, `branch`, `rebase`) cover the history-rewriting and remote-overwriting surface as of git 2.x. If a new git subcommand grows a destructive `-f` mode, the spec gets a follow-up.
- **Operator runs an aliased git wrapper** (`hub`, `gh`-as-git, custom function): the regex anchors on the literal `git` command word. Aliased wrappers bypass the check today and continue to bypass it after this change. Out of scope.

## Out of scope

- Auditing the broader `/ship` guardrails surface for other false-positive flag checks. If new ones surface during future ship runs, they get their own ticket.
- Porting the `/ship` validator into this plugin. The skill is intentionally personal and operator-local.
- Telemetry on how often the bare `-f` check tripped historically. The CCE-75 polish run is the recorded instance; counting prior occurrences across operator logs is not worth the dig.

Co-authored-by: Claude Opus 4.7 <noreply@anthropic.com>

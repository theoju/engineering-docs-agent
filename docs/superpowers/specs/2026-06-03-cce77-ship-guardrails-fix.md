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
- Test harness: `~/.claude/skills/ship/tests/validate-git-cmd.test.sh` — existing Bash harness with a `run_validator` helper and inline `assert_exit "$rc" "<expected>" "<label>"` calls. New cases follow this style; do **not** introduce pytest-style `test_*` functions.

Spec is authored against `~/.claude/skills/ship/lib/validate-git-cmd.sh:40`. The shim stays as-is.

## Problem

The `/ship` PreToolUse guardrails hook blocks any Bash command containing a whitespace-bounded `-f` token, on the assumption that `-f` means `git push --force`. In practice many legitimate shell commands use `-f` as a non-destructive flag and get falsely blocked mid-ship:

- `rm -f <known-temp-file>` — `-f` means "ignore nonexistent" (idempotent cleanup). **This is the documented incident.**
- `find <path> -f` — `-f` is a follow-symlinks flag in some BSD `find` variants. Reasonable extrapolation.
- `gh` and other CLI tools using `-f` as a force/format/file flag — covered as the "other tools" representative.

The regression surfaced during the CCE-75 polish `/ship` run for PR #98. The cleanup step `rm -f /tmp/.ship-active /tmp/ship-state-1512165.json` was blocked even though `rm -f` cannot affect git history. Workaround was trivial — split the cleanup into two Bash calls — but it is a recurring papercut on otherwise-clean ship runs.

## Current behavior

`~/.claude/skills/ship/lib/validate-git-cmd.sh:40` does a whitespace-bounded token check:

```bash
if [[ " $CMD " == *" -f "* ]]; then
  block "-f"
fi
```

This matches `-f` as a standalone token regardless of which command word it modifies. The long-form flag checks elsewhere in the validator (`--no-verify`, `--amend`, `--force`, `--force-with-lease`) are correctly scoped to git operations and stay as-is.

The validator runs under `set -u` (`validate-git-cmd.sh:13`). Any unbound variable in the new code crashes the hook with a confusing `unbound variable` error instead of a guardrail message, so the replacement code must avoid referencing variables outside of `BASH_REMATCH`.

The validator uses `#!/usr/bin/env bash`. On macOS — the host platform for `/ship` — system bash is **3.2.57**, which has a known parser quirk in `[[ ... =~ <inline-pattern> ... ]]`: metacharacters like `;`, `&`, `|`, `(`, and backtick inside a leading bracket class are mis-tokenized when the pattern is inline. The pattern must be assigned to a variable first and dereferenced in the conditional. This is not a hypothetical — the obvious inline form of the regex below was empirically observed to emit `syntax error in conditional expression: unexpected token ';'` under macOS bash 3.2.57, which would crash the hook on every Bash PreToolUse. The variable form parses cleanly and produces identical match behavior across the full test plan.

## Goal

`-f` blocks only when it is an argument to a git operation that has a real destructive `-f` short flag. Every other `-f` use — `rm`, `find`, `gh`, `tar`, `cp`, `mv`, `ln`, `mkdir`, `chmod`, `chown`, `unzip`, and so on — flows through. The existing long-form checks survive verbatim.

## Non-goals

- Loosening the long-form checks. `--force`, `--force-with-lease`, `--amend`, `--no-verify` stay as block conditions, regression-guarded.
- A general-purpose shell parser. The validator runs on every Bash PreToolUse and must stay fast and dependency-free. A regex with explicit git command words is enough.
- Touching the hook shim at `~/.claude/hooks/ship-guardrails.sh`. The shim only forwards `$CMD` to the validator; no logic change is needed there.
- Catching `-f` inside aliased git wrappers (`hub`, custom shell functions, `git -C <path>`, `git -c key=val`). Documented and accepted in Risk below.

## Design

### Path chosen: git-aware regex

Replace the bare token check with a regex that requires `-f` to follow a `git <subcommand>` prefix on the same command segment. The regex pattern is assigned to a variable before the `[[ =~ ]]` conditional — see the bash 3.2 note below.

```bash
# Block -f only on git subcommands that actually accept -f as a destructive flag.
# Segment boundary at the start: line start, ;, &, |, (, backtick, or whitespace.
# Subcommand list trimmed to those with real destructive -f short flags as of git 2.x:
#   push -f      → force-push (rewrites remote history)
#   checkout -f  → discard local changes, overwrite untracked
#   clean -f     → delete untracked files (requires -f to act at all)
#   branch -f    → force-move branch ref (rewrites local history pointer)
#   tag -f       → force-move tag ref
#
# Trailing flag-char class `-f[A-Za-z]*` catches bundled short-flag sets like
# `git clean -fd` (the form `git status` suggests to users). See the bundled-flag
# discussion below.
#
# IMPORTANT: pattern is assigned to a variable, then referenced. macOS system bash
# (3.2.57) does NOT parse this pattern inline in `[[ =~ ]]` — the leading bracket
# class contains `;`, `&`, `|`, `(`, backtick, which trip the 3.2 conditional
# parser ("syntax error in conditional expression: unexpected token ';'"). The
# variable form parses cleanly on 3.2 and on modern bash. A `bash -n` syntax
# check in the test harness guards against future inlining.
FORCE_F_RE='(^|[\;\&\|\(\`[:space:]])git[[:space:]]+(push|checkout|clean|branch|tag)[^|;&]*[[:space:]]-f[A-Za-z]*([[:space:]]|$)'
if [[ "$CMD" =~ $FORCE_F_RE ]]; then
  block "-f (on git ${BASH_REMATCH[2]})"
fi
```

Key design choices:

- **Pattern assigned to a variable.** macOS bash 3.2.57 (the system bash on the platform that runs `/ship`) refuses to parse an inline `[[ "$CMD" =~ (^|[\;\&\|\(\`[:space:]])... ]]`pattern. The variable form`[["$CMD" =~ $FORCE_F_RE]]`parses correctly on bash 3.2 and on modern bash, and produces identical match behavior across the full test plan. A future refactor that innocently inlines the pattern is caught by the`bash -n` parse check in the harness (see Test plan).
- **Subcommand list trimmed to real `-f` short flags.** The earlier draft included `commit`, `reset`, `rebase`; none of these accept `-f` as a destructive short flag in modern git (`git commit -F` is `--file`, not force; `reset` and `rebase` have no `-f`). Including them paid for regex surface and test obligations against behavior that does not exist. The long-form `--amend` / `--no-verify` / `--force` checks elsewhere in the validator still cover the realistic commit-time hazards.
- **`tag` added.** `git tag -f v1.0` force-moves a tag — a real history-rewriting `-f` short flag the previous list missed.
- **Leading segment-boundary class includes `(` and backtick.** Without those, `$(git push -f ...)` and `` `git push -f ...` `` slip through silently. These are real forms inside `bash -c` payloads and CI scripts. Adding them keeps the guarantee aligned with the spec's framing.
- **Trailing `-f[A-Za-z]*` catches bundled short-flag sets.** `git clean -fd` is the form `git status` itself suggests to users and is what most operators type. The bare `-f` form would let bundled invocations slip through silently. The trailing `[A-Za-z]*` class matches `-f`, `-fd`, `-fdx`, etc., while still requiring whitespace or end-of-string immediately after. Decision committed in spec rather than deferred to implementation.
- **Subcommand captured via `BASH_REMATCH[2]`.** The block message uses `${BASH_REMATCH[2]}`, not a free `$cmd` variable. Under `set -u`, a bare `$cmd` would crash the hook with `unbound variable`. `BASH_REMATCH` is set by the immediately preceding `=~` match and is safe to dereference.
- **`[^|;&]*` segment-isolation clause kept.** It is two characters of regex and meaningfully prevents future false positives like `git status | rm -f /tmp/x` from blocking. Tests below pin both the pass case (`-f` belongs to `rm`) and the inverse block case (`echo foo | git push -f` — `-f` belongs to git).

### Accepted conservative behavior: literal text in arguments

The regex matches the literal text `git <sub> ... -f` anywhere inside a command segment. Strings like `echo "history: git push -f was run yesterday"` or `grep "git push -f" log.txt` will block. This is the same conservative posture the existing validator takes for long-form flags (see `tests/validate-git-cmd.test.sh:39-40`, where `grep -- --amend file.txt` blocks). Accepted as the cheap, safe default. A test case pins it.

### Alternative considered: leading-command allowlist

Maintain an allowlist of safe commands (`rm`, `find`, `gh`, `tar`, `cp`, `mv`, `ln`, `mkdir`, `chmod`, `chown`, `unzip`) and skip the `-f` check when the leading command word is in the allowlist.

Rejected because:

- It enumerates the world's safe commands instead of the small set of dangerous ones. New CLIs that use `-f` (and there are many) keep tripping until the allowlist catches up.
- A command like `cd /tmp && rm -f x` would need either segment-aware parsing (which the chosen design already does) or a second rule, doubling the surface.
- The git-aware regex is the inversion that the validator's other checks already use for long-form flags — it keeps the file internally consistent.

## Acceptance criteria

1. `rm -f <path>` does **not** block inside `/ship`.
2. `find . -name foo -f` does **not** block inside `/ship`.
3. `git push -f origin main` **does** block inside `/ship`. Stderr mentions `-f (on git push)`.
4. `git push --force origin main` **does** block (existing long-form check, regression-guarded).
5. `git push --force-with-lease` **does** block (existing check).
6. `git commit --amend` **does** block (existing check).
7. `git commit --no-verify` **does** block (existing check).
8. A new test covers each block + pass case enumerated in the Test plan below.
9. The hook shim at `~/.claude/hooks/ship-guardrails.sh` is unchanged.
10. The validator does **not** exit with `unbound variable` when the `-f` block fires (regression guard for the `set -u` interaction with `BASH_REMATCH`), and stderr does **not** contain `syntax error` (regression guard against the bash 3.2 inline-regex parse pitfall).
11. The validator source assigns the regex pattern to a variable; an inline `[[ ... =~ <pattern> ... ]]` form is rejected by code review because it fails to parse on bash 3.2. The harness runs `bash -n` against the validator as a precondition and the test fails if the validator does not parse under host bash.

## Test plan

Tests live in the existing harness at `~/.claude/skills/ship/tests/validate-git-cmd.test.sh`. The harness sources a `run_validator` helper that passes a JSON `tool_input` shape into the validator and captures `$rc` plus stderr. New cases follow the existing inline style: `assert_exit "$rc" "<expected>" "<label>"`. No new test file is needed.

### Parse-check precondition

Before any case runs, the harness calls `bash -n "$LIB" || fail "validator does not parse under host bash"` where `$LIB` points at `~/.claude/skills/ship/lib/validate-git-cmd.sh`. This single line catches the entire class of bash 3.2 inline-regex parse failures at test time and any future syntax regression.

### Pass cases (legitimate `-f` use)

- `assert_exit "$rc" "0" "rm -f passes"` — `CMD="rm -f /tmp/foo"`.
- `assert_exit "$rc" "0" "find -f passes"` — `CMD="find . -name foo -f"`.
- `assert_exit "$rc" "0" "gh -f passes"` — `CMD="gh pr create -f"`. (Other-tools representative.)
- `assert_exit "$rc" "0" "pipeline isolates -f to non-git segment"` — `CMD="git status | rm -f /tmp/x"`.

### Block cases on git subcommands with real `-f` (full subcommand-list contract)

- `assert_exit "$rc" "2" "git push -f blocks"` — `CMD="git push -f origin main"`. Stderr asserted to contain `-f (on git push)`.
- `assert_exit "$rc" "2" "git checkout -f blocks"` — `CMD="git checkout -f main"`. Stderr contains `-f (on git checkout)`.
- `assert_exit "$rc" "2" "git clean -f -d blocks (separated form)"` — `CMD="git clean -f -d"`. Stderr contains `-f (on git clean)`.
- `assert_exit "$rc" "2" "git clean -fd blocks (bundled form)"` — `CMD="git clean -fd"`. Stderr contains `-f (on git clean)`. Pins the trailing `[A-Za-z]*` clause.
- `assert_exit "$rc" "2" "git branch -f blocks"` — `CMD="git branch -f feature-x main"`. Stderr contains `-f (on git branch)`.
- `assert_exit "$rc" "2" "git tag -f blocks"` — `CMD="git tag -f v1.0"`. Stderr contains `-f (on git tag)`.

### Block cases on segment-boundary forms (the regex's leading-anchor contract)

- `assert_exit "$rc" "2" "chained git push -f blocks"` — `CMD="cd /tmp && git push -f origin main"`.
- `assert_exit "$rc" "2" "command-substitution git push -f blocks"` — `CMD='echo $(git push -f origin main)'`. Exercises the `(` anchor.
- `assert_exit "$rc" "2" "backtick git push -f blocks"` — ``CMD='echo `git push -f origin main`'``. Exercises the backtick anchor.
- `assert_exit "$rc" "2" "pipeline routes -f to git push"` — `CMD="echo foo | git push -f origin main"`. The `-f` belongs to git, not the upstream `echo`.

### Conservative-block acceptance case

- `assert_exit "$rc" "2" "literal text containing git push -f blocks (accepted conservative)"` — `CMD='echo "history: git push -f was run yesterday"'`. Documents the deliberate conservative posture; mirrors the existing `grep -- --amend file.txt` behavior in the test file.

### Regression guards on existing long-form checks

- `assert_exit "$rc" "2" "git push --force blocks"` — `CMD="git push --force origin main"`.
- `assert_exit "$rc" "2" "git push --force-with-lease blocks"` — `CMD="git push --force-with-lease"`.
- `assert_exit "$rc" "2" "git commit --amend blocks"` — `CMD="git commit --amend"`.
- `assert_exit "$rc" "2" "git commit --no-verify blocks"` — `CMD="git commit --no-verify"`.

### `set -u` and bash-parse regression guards

- `assert_exit "$rc" "2" "block message uses BASH_REMATCH, no unbound-variable crash"` — `CMD="git push -f origin main"` under `set -u`. Capture stderr into `$err` and run `assert_stderr_not_contains "$err" "unbound variable" "no unbound-variable crash on block fire"`.
- `assert_stderr_not_contains "$err" "syntax error" "no bash parse error on block fire"` — sibling assertion against the same captured stderr. Catches the bash 3.2 inline-regex parse failure even if the parse-check precondition is bypassed (defense-in-depth).
- If `assert_stderr_not_contains` does not exist, add the helper to the harness alongside `assert_exit`; trivial wrapper around `grep -vF -q`.

## Behavior matrix

| Command                               | Existing behavior  | Behavior after CCE-77              |
| ------------------------------------- | ------------------ | ---------------------------------- |
| `rm -f /tmp/foo`                      | block (false trip) | pass                               |
| `find . -name foo -f`                 | block (false trip) | pass                               |
| `gh pr create -f`                     | block (false trip) | pass                               |
| `git push -f origin main`             | block (correct)    | block (correct, narrowed)          |
| `git checkout -f main`                | block (correct)    | block (correct, narrowed)          |
| `git clean -f -d`                     | block (correct)    | block (correct, narrowed)          |
| `git clean -fd`                       | block (correct)    | block (correct, bundled form)      |
| `git branch -f feature-x main`        | block (correct)    | block (correct, narrowed)          |
| `git tag -f v1.0`                     | block (correct)    | block (correct, narrowed)          |
| `git push --force origin main`        | block (long-form)  | block (long-form, unchanged)       |
| `git push --force-with-lease`         | block (long-form)  | block (long-form, unchanged)       |
| `git commit --amend`                  | block (long-form)  | block (long-form, unchanged)       |
| `git commit --no-verify`              | block (long-form)  | block (long-form, unchanged)       |
| `git status \| rm -f /tmp/x`          | block (false trip) | pass                               |
| `echo foo \| git push -f origin main` | block (correct)    | block (correct)                    |
| `cd /tmp && git push -f origin main`  | block (correct)    | block (correct)                    |
| `$(git push -f origin main)`          | block (correct)    | block (correct)                    |
| `` `git push -f origin main` ``       | block (correct)    | block (correct)                    |
| `echo "history: git push -f was run"` | block (false trip) | block (accepted conservative)      |
| `git -C /repo push -f origin main`    | block (correct)    | **pass** (known bypass — see Risk) |
| `git -c http.sslVerify=false push -f` | block (correct)    | **pass** (known bypass — see Risk) |

## Files changed

- `~/.claude/skills/ship/lib/validate-git-cmd.sh` — replace the bare `-f` token check at line 40 with the git-aware regex; surrounding block (lines 30-44) stays in place. The regex pattern is assigned to a variable (`FORCE_F_RE=...`) before the `[[ =~ ]]` conditional.
- `~/.claude/skills/ship/tests/validate-git-cmd.test.sh` — append the new cases above, matching the existing inline `assert_exit` style. Add the `bash -n` parse-check precondition at harness start. If `assert_stderr_not_contains` does not exist, add the helper alongside the existing `assert_exit`.

No changes to:

- `~/.claude/hooks/ship-guardrails.sh` (14-line shim).
- The long-form flag checks elsewhere in `validate-git-cmd.sh`.
- This repo (`engineering-docs-agent`). The spec is archived here for cross-referencing during future CCE work.

## Risk

- **Regression on legitimate force-push blocks**: mitigated by the explicit regression-guard cases in the test plan (`--force`, `--force-with-lease`, `--amend`, `--no-verify`).
- **Subcommand list drifts behind git**: the chosen subcommands (`push`, `checkout`, `clean`, `branch`, `tag`) cover the real destructive `-f` short-flag surface as of git 2.x. If a new git subcommand grows a destructive `-f` mode, the spec gets a follow-up.
- **`set -u` interaction**: the validator runs under `set -u`. The new code references `${BASH_REMATCH[2]}`, which is set by the preceding `=~` match. A dedicated test asserts the validator does not exit with `unbound variable` when the block fires. Any future edit that references an unset variable in this block must be caught by the same test.
- **Bash 3.2 inline-regex parse failure**: macOS system bash (3.2.57) does not parse the chosen pattern inline in `[[ =~ ]]`. The design assigns the pattern to `FORCE_F_RE` before the conditional. Two test-time guards back this up: a `bash -n` parse-check precondition at harness start, and an `assert_stderr_not_contains "$err" "syntax error" ...` sibling to the `unbound variable` guard. A future refactor that inlines the pattern is caught at test time.
- **`git -C <path>` and `git -c key=val` global-option bypass**: the regex anchors on `git[[:space:]]+(push|...)`, requiring the subcommand to immediately follow `git`. Invocations like `git -C /repo push -f origin main` or `git -c http.sslVerify=false push -f` bypass the check. **Documented and accepted as out-of-scope for this ticket.** Extending the regex to skip global options (something like `git[[:space:]]+(-[A-Za-z][[:space:]]+\S+[[:space:]]+|-[A-Za-z][[:space:]]+)*(push|...)`) is a follow-up if the bypass shows up in a real ship run. Tracking commitment matches the aliased-wrapper case below.
- **Operator runs an aliased git wrapper** (`hub`, `gh`-as-git, custom shell function): the regex anchors on the literal `git` command word. Aliased wrappers bypass the check today and continue to bypass it after this change. Out of scope; follow-up only if it surfaces in a real ship run.
- **Bundled short-flag sets**: committed in design — the trailing `-f[A-Za-z]*` clause matches `-f`, `-fd`, `-fdx`, etc. Both separated (`git clean -f -d`) and bundled (`git clean -fd`) forms block. Pinned by two distinct test cases.

## Out of scope

- Auditing the broader `/ship` guardrails surface for other false-positive flag checks. If new ones surface during future ship runs, they get their own ticket.
- Porting the `/ship` validator into this plugin. The skill is intentionally personal and operator-local.
- Telemetry on how often the bare `-f` check tripped historically. The CCE-75 polish run is the recorded instance; counting prior occurrences across operator logs is not worth the dig.
- Catching `git -C` / `git -c` global-option bypasses, and catching aliased git wrappers. Both are real but unobserved in ship runs; follow-up if evidence appears.

Co-authored-by: Claude Opus 4.7 <noreply@anthropic.com>

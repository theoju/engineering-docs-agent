# CCE-77 — Narrow `/ship` Guardrails `-f` Token Check Implementation Plan

> **Status (2026-06-04):** CCE-77 shipped a minimal **v1 glob-based** fix (token-boundary `" $CMD " == *" -f "*` gated by `git push` / `git commit` substring checks — see `docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md` "Implementation note (v1, 2026-06-04)"). This plan describes the **full regex-based target design** (covers `git checkout/clean/branch/tag -f` too) and is preserved as the reference for a future regex-upgrade follow-up. The v1 fix and this plan diverge intentionally; do not execute this plan as-is against the already-patched validator.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bare `-f` token check in `~/.claude/skills/ship/lib/validate-git-cmd.sh:40` with a git-aware regex that only blocks `-f` when it follows a git subcommand with a real destructive `-f` short flag (`push`, `checkout`, `clean`, `branch`, `tag`), while preserving every existing long-form block (`--no-verify`, `--amend`, `--force`, `--force-with-lease`).

**Architecture:** Pure shell. The validator is a 45-line bash script with no runtime deps beyond `jq` and bash itself. Detection moves from a lexical token-presence check to a regex match anchored on segment boundaries (`^`, `;`, `&`, `|`, `(`, backtick, whitespace) and an enumerated git subcommand list. The regex pattern is **assigned to a variable** before the `[[ =~ ]]` conditional because macOS system bash 3.2.57 mis-parses the bracket class inline. Tests live in the existing bash harness at `~/.claude/skills/ship/tests/validate-git-cmd.test.sh` and follow the existing inline `assert_exit` style. No commits — the orchestrator captures a forensic patch via `git diff --no-index` against the pre-image saved at `validate-git-cmd.test.sh.orig`.

**Tech Stack:** Bash 3.2+ (macOS system bash compatible), `jq` for JSON parsing, the project's existing `run.sh` test harness (`assert_eq` / `assert_exit`).

---

## Execution constraints (read before Task 1)

- **Detached target.** The files under modification live in `~/.claude/skills/ship/` and are not in any git repository. Treat each edit as a direct filesystem write. The orchestrator will capture a forensic patch separately (Task 7).
- **Test runner.** `bash ~/.claude/skills/ship/tests/validate-git-cmd.test.sh` — but the file is a source-able fragment, not a standalone script. To run it: `bash ~/.claude/skills/ship/tests/run.sh` (the harness driver sources every `*.test.sh` in the dir, totals pass/fail, exits nonzero on any fail).
- **No commits.** This plan does not run `git add` / `git commit`. The orchestrator handles forensic capture in Task 7.
- **Patch artifact.** Save a `git diff --no-index` style unified diff of the before/after to `$HOME/.claude/orchestrator/detached-changes/B11.patch`. Use the `.orig` baseline already on disk for `validate-git-cmd.test.sh`; for the validator, snapshot the current contents before editing.
- **Spec authority.** The plan's design follows `docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md` (second-pass approved 2026-06-04 per observation 8359). The orchestrator's B11 patch-spec proposed an alternative HAS_GIT/HAS_GIT_PUSH gating framing; the spec's git-aware regex framing wins because acceptance criteria #3 pins the stderr format `-f (on git push)` to the regex's `${BASH_REMATCH[2]}` capture and acceptance criterion #11 pins the variable-assigned regex as the design.
- **Pre-existing partial work.** Observation 8368 records that lines 58-89 of `validate-git-cmd.test.sh` already contain Cases 11-17 (rm/mv/find/grep/tar pass + git push -f/--force block) added during scaffolding. Treat those cases as fixtures to keep; this plan only adds the remaining cases the spec requires (segment boundary, bundled, command substitution, backtick, pipeline routing, parse-check precondition, `set -u` guard, stderr capture for `-f (on git push)` literal, plus bash 3.2 parse-error guard).

## File structure

- **Modify:** `~/.claude/skills/ship/lib/validate-git-cmd.sh` — replace line 40-42 bare `-f` token check with the variable-assigned regex; surrounding code at lines 28-38 (block fn + long-form checks) stays as-is. Keep the file under 60 lines.
- **Modify:** `~/.claude/skills/ship/tests/validate-git-cmd.test.sh` — append spec-required test cases past line 89; add `bash -n` parse-check precondition just after line 1 (`LIB=...`); add `assert_stderr_not_contains` helper to `run.sh` (the harness driver) if it does not exist.
- **Modify (helper, if missing):** `~/.claude/skills/ship/tests/run.sh` — add `assert_stderr_not_contains` alongside `assert_exit` / `assert_eq`. Trivial wrapper around `grep -vF -q`.
- **Snapshot (read-only):** `~/.claude/skills/ship/tests/validate-git-cmd.test.sh.orig` — already on disk. The forensic patch uses it as the pre-image baseline for the test file.
- **Write:** `$HOME/.claude/orchestrator/detached-changes/B11.patch` — forensic unified diff captured in Task 7.

Each task is self-contained and produces a runnable state. After Task 6 the patched system passes its own test suite; Task 7 is purely artifact capture.

---

## Task 1: Snapshot current validator for forensic baseline

**Files:**

- Read: `~/.claude/skills/ship/lib/validate-git-cmd.sh`
- Create: `/tmp/cce77-validate-git-cmd.sh.orig`

- [ ] **Step 1: Copy the current validator to a stable baseline**

Run:

```bash
cp ~/.claude/skills/ship/lib/validate-git-cmd.sh /tmp/cce77-validate-git-cmd.sh.orig
```

Expected: command returns 0; `/tmp/cce77-validate-git-cmd.sh.orig` exists and is byte-identical to the source.

- [ ] **Step 2: Verify the baseline**

Run:

```bash
diff -q ~/.claude/skills/ship/lib/validate-git-cmd.sh /tmp/cce77-validate-git-cmd.sh.orig && echo "BASELINE OK"
```

Expected: `BASELINE OK` printed; exit 0.

- [ ] **Step 3: Confirm the line-40 token check matches the spec's "current behavior" excerpt**

Run:

```bash
sed -n '38,42p' /tmp/cce77-validate-git-cmd.sh.orig
```

Expected output (exact):

```
[[ "$CMD" == *"--force"* ]] && block "--force"
# Short -f: must be a token (preceded by space, followed by space or end of string).
if [[ " $CMD " == *" -f "* ]]; then
  block "-f"
fi
```

If the lines do not match, **STOP** and report. The spec is authored against this exact baseline; if line 40 differs, downstream patching assumptions break.

---

## Task 2: Add `assert_stderr_not_contains` helper to the harness driver

**Files:**

- Modify: `~/.claude/skills/ship/tests/run.sh` (insert after `assert_exit` block, before `DIR=...` on line 30)

- [ ] **Step 1: Confirm the helper does not already exist**

Run:

```bash
grep -n 'assert_stderr_not_contains' ~/.claude/skills/ship/tests/run.sh ; echo "exit=$?"
```

Expected: no match, `exit=1`. If exit is 0, the helper exists — skip to Task 3.

- [ ] **Step 2: Insert the helper between `assert_exit` and the DIR loop**

Edit `~/.claude/skills/ship/tests/run.sh`. After the closing `}` of `assert_exit` on line 28 and before the blank line preceding `DIR=$(...)` on line 30, insert:

```bash
assert_stderr_not_contains() {
  local stderr="$1" needle="$2" label="${3:-}"
  if grep -vF -q -- "$needle" <<<"$stderr"; then
    # grep -vF -q exits 0 if any line did NOT match the needle.
    # That's an unreliable inversion — use a direct presence test instead.
    :
  fi
  if grep -F -q -- "$needle" <<<"$stderr"; then
    echo "FAIL [$HARNESS_NAME] ${label:-(no label)}: stderr unexpectedly contained '$needle': $stderr"
    HARNESS_FAIL=$((HARNESS_FAIL+1))
  else
    HARNESS_PASS=$((HARNESS_PASS+1))
  fi
}
```

(The `grep -vF -q` block above is intentionally a no-op — `grep -vF -q` returns 0 if any line in the input does not match the needle, which inverts wrong for our use case. The actual presence check is the second `grep -F -q` block. Keeping the comment above as a guard against a future refactor that "simplifies" by removing the explanation.)

- [ ] **Step 3: Parse-check the harness driver**

Run:

```bash
bash -n ~/.claude/skills/ship/tests/run.sh && echo "PARSE OK"
```

Expected: `PARSE OK`; exit 0.

- [ ] **Step 4: Smoke the helper**

Run:

```bash
bash -c '
  source ~/.claude/skills/ship/tests/run.sh 2>/dev/null || true
  HARNESS_NAME=smoke
  HARNESS_PASS=0
  HARNESS_FAIL=0
  # Re-source just the helper definitions; the for-loop above will have run.
  # Pull the helper inline for verification:
  assert_stderr_not_contains() {
    local stderr="$1" needle="$2" label="${3:-}"
    if grep -F -q -- "$needle" <<<"$stderr"; then
      echo "FAIL"; HARNESS_FAIL=$((HARNESS_FAIL+1))
    else
      HARNESS_PASS=$((HARNESS_PASS+1))
    fi
  }
  assert_stderr_not_contains "hello world" "syntax error" "no-match should pass"
  assert_stderr_not_contains "syntax error" "syntax error" "match should fail"
  echo "PASS=$HARNESS_PASS FAIL=$HARNESS_FAIL"
'
```

Expected output last line:

```
PASS=1 FAIL=1
```

The smoke confirms the helper increments PASS on absence and FAIL on presence.

---

## Task 3: Write failing tests for the spec's new pass/block cases

**Files:**

- Modify: `~/.claude/skills/ship/tests/validate-git-cmd.test.sh` (append after line 89)

This task adds every test case in the spec's "Test plan" section that is not already covered by Cases 1-17 (lines 11-89). Tests are added FIRST; they fail against the current validator (because the regex is not yet in place). They pass after Task 5.

- [ ] **Step 1: Confirm the existing CCE-77 partial cases are in place**

Run:

```bash
sed -n '58,89p' ~/.claude/skills/ship/tests/validate-git-cmd.test.sh
```

Expected: Cases 11-17 from observation 8368 — `rm -f`, `mv -f`, `find -f`, `grep -f`, `tar -f` (all `exit 0`); `git push -f` and `git push --force` (both `exit 2`). If these are missing, **STOP** and report — this plan assumes they exist.

- [ ] **Step 2: Append the parse-check precondition at the top of the test file**

The harness sources each `*.test.sh` file; insertion at the very top of the test fragment means it runs before any case in the fragment. The harness `DIR` variable is not visible at source-time of the test file (it is defined in `run.sh` before the loop), but the test file does have `$DIR` because the loop sets it before `source`. The validator path resolves through the existing `LIB="$DIR/../lib/validate-git-cmd.sh"` on line 1.

Edit `~/.claude/skills/ship/tests/validate-git-cmd.test.sh`. Replace the existing line 1 (`LIB="$DIR/../lib/validate-git-cmd.sh"`) with:

```bash
LIB="$DIR/../lib/validate-git-cmd.sh"

# CCE-77 parse-check precondition: catch bash 3.2 inline-regex failures and any
# future syntax regression in the validator. Runs before any test case below.
if ! bash -n "$LIB" 2>/tmp/ship-validator-parse-err; then
  echo "FAIL [$HARNESS_NAME] validator does not parse under host bash: $(cat /tmp/ship-validator-parse-err)"
  HARNESS_FAIL=$((HARNESS_FAIL+1))
fi
rm -f /tmp/ship-validator-parse-err
```

- [ ] **Step 3: Append the new spec-required test cases at end of file**

Edit `~/.claude/skills/ship/tests/validate-git-cmd.test.sh`. After the final line (Case 17, `assert_exit "$rc" "2" "git push --force still blocked (CCE-77)"`), append:

```bash

# CCE-77 (cont.): spec-required cases beyond the scaffolded baseline.

# Pass cases — additional legitimate -f use the spec enumerates.
# Case 18: gh -f (other-tools representative).
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"gh pr create -f"}}')
assert_exit "$rc" "0" "gh -f passes (CCE-77)"

# Case 19: pipeline isolates -f to non-git segment.
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git status | rm -f /tmp/x"}}')
assert_exit "$rc" "0" "pipeline isolates -f to non-git segment (CCE-77)"

# Block cases — full git subcommand contract (push already pinned in Cases 16/17).

# Case 20: git checkout -f blocks.
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git checkout -f main"}}')
assert_exit "$rc" "2" "git checkout -f blocks (CCE-77)"

# Case 21: git clean -f -d blocks (separated form).
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git clean -f -d"}}')
assert_exit "$rc" "2" "git clean -f -d blocks separated (CCE-77)"

# Case 22: git clean -fd blocks (bundled form — pins the trailing [A-Za-z]* clause).
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git clean -fd"}}')
assert_exit "$rc" "2" "git clean -fd blocks bundled (CCE-77)"

# Case 23: git branch -f blocks.
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git branch -f feature-x main"}}')
assert_exit "$rc" "2" "git branch -f blocks (CCE-77)"

# Case 24: git tag -f blocks.
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git tag -f v1.0"}}')
assert_exit "$rc" "2" "git tag -f blocks (CCE-77)"

# Block cases — segment-boundary forms (regex leading-anchor contract).

# Case 25: chained git push -f blocks.
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"cd /tmp && git push -f origin main"}}')
assert_exit "$rc" "2" "chained git push -f blocks (CCE-77)"

# Case 26: command-substitution git push -f blocks (exercises ( anchor).
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"echo $(git push -f origin main)"}}')
assert_exit "$rc" "2" "command-substitution git push -f blocks (CCE-77)"

# Case 27: backtick git push -f blocks (exercises backtick anchor).
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"echo `git push -f origin main`"}}')
assert_exit "$rc" "2" "backtick git push -f blocks (CCE-77)"

# Case 28: pipeline routes -f to git push (the -f belongs to git, not echo).
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"echo foo | git push -f origin main"}}')
assert_exit "$rc" "2" "pipeline routes -f to git push (CCE-77)"

# Case 29: conservative-block acceptance — literal text containing git push -f.
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"echo \"history: git push -f was run yesterday\""}}')
assert_exit "$rc" "2" "literal text git push -f blocks (CCE-77 accepted conservative)"

# Case 30: set -u + BASH_REMATCH regression guard + stderr literal contract.
# Captures stderr, asserts exit 2, asserts no 'unbound variable' / 'syntax error'
# trace, and asserts the stderr contains the spec-pinned literal '-f (on git push)'.
echo '{"tool_name":"Bash","tool_input":{"command":"git push -f origin main"}}' | bash "$LIB" 2>/tmp/ship-validator-stderr >/dev/null
rc=$?
err=$(cat /tmp/ship-validator-stderr)
assert_exit "$rc" "2" "set -u: git push -f still blocks (CCE-77)"
assert_stderr_not_contains "$err" "unbound variable" "no unbound-variable crash on block fire (CCE-77)"
assert_stderr_not_contains "$err" "syntax error" "no bash parse error on block fire (CCE-77)"
if [[ "$err" == *"-f (on git push)"* ]]; then
  HARNESS_PASS=$((HARNESS_PASS+1))
else
  echo "FAIL [$HARNESS_NAME]: stderr did not contain '-f (on git push)': $err"
  HARNESS_FAIL=$((HARNESS_FAIL+1))
fi
rm -f /tmp/ship-validator-stderr
```

- [ ] **Step 4: Run the harness and confirm the new cases FAIL against the unpatched validator**

Run:

```bash
bash ~/.claude/skills/ship/tests/run.sh ; echo "exit=$?"
```

Expected:

- Cases 1-17 pass (the existing scaffolded suite).
- Case 18 (`gh pr create -f`) — **FAIL** (current validator blocks bare `-f`).
- Case 19 (`git status | rm -f /tmp/x`) — **FAIL** (current validator blocks).
- Cases 20-24 (`git checkout -f`, `git clean -f -d`, `git clean -fd`, `git branch -f`, `git tag -f`) — pass under current validator (it blocks on bare `-f`), so they PASS now and continue to pass after Task 5. Acceptable.
- Cases 25-29 (chained / `$()` / backtick / pipeline-to-git / literal-text) — all involve `-f` as a token somewhere, so the current validator blocks them and they PASS now. They continue to pass after Task 5 (the new regex catches the same patterns). Acceptable.
- Case 30 stderr-literal check — **FAIL** (current validator stderr is `blocked '-f' inside /ship session...`, not `-f (on git push)`).

Net: at least Cases 18, 19, and the stderr-literal segment of Case 30 must fail. Final harness exit is nonzero. If every new case passes against the unpatched validator, the regex anchoring is not being tested — **STOP** and re-check the test additions.

---

## Task 4: Snapshot validator state and re-verify failures pre-edit

**Files:**

- Read: `~/.claude/skills/ship/lib/validate-git-cmd.sh`

- [ ] **Step 1: Re-run the harness, capture pass/fail tallies**

Run:

```bash
bash ~/.claude/skills/ship/tests/run.sh 2>&1 | tail -5
```

Expected: tallies show `Failed:` count ≥ 3 (the cases enumerated in Task 3 Step 4). Note the exact tally.

- [ ] **Step 2: Confirm the validator is still the original baseline**

Run:

```bash
diff -q ~/.claude/skills/ship/lib/validate-git-cmd.sh /tmp/cce77-validate-git-cmd.sh.orig && echo "VALIDATOR UNCHANGED"
```

Expected: `VALIDATOR UNCHANGED`. The TDD red-state is real — failures come from the test additions, not from a partial edit.

---

## Task 5: Patch the validator with the git-aware regex

**Files:**

- Modify: `~/.claude/skills/ship/lib/validate-git-cmd.sh` (lines 39-42, the bare `-f` block)

- [ ] **Step 1: Replace lines 39-42 with the variable-assigned regex block**

Edit `~/.claude/skills/ship/lib/validate-git-cmd.sh`. Replace the existing lines 39-42:

```bash
# Short -f: must be a token (preceded by space, followed by space or end of string).
if [[ " $CMD " == *" -f "* ]]; then
  block "-f"
fi
```

with:

```bash
# Short -f: block only when it follows a git subcommand that has a real
# destructive -f short flag (push, checkout, clean, branch, tag).
#
# Segment-boundary leading class: ^, ;, &, |, (, backtick, whitespace — covers
# pipelines, &&-chains, command substitution, backtick subshells, and plain
# leading position. The [^|;&]* clause keeps the match inside one command
# segment (so `git status | rm -f /tmp/x` does not trip).
#
# Trailing [A-Za-z]* on -f matches bundled short-flag sets like `git clean -fd`
# (what `git status` itself suggests). The closing ([[:space:]]|$) keeps the
# token boundary discipline.
#
# IMPORTANT: pattern assigned to FORCE_F_RE, then dereferenced in [[ =~ ]].
# macOS system bash 3.2.57 fails to parse this pattern INLINE (the leading
# bracket class contains ;, &, |, (, backtick — trips the 3.2 conditional
# parser with "syntax error in conditional expression: unexpected token ';'").
# The variable form parses cleanly on 3.2 and on modern bash. The test harness
# runs `bash -n` against this file as a precondition and will fail any future
# refactor that innocently inlines the pattern.
FORCE_F_RE='(^|[;&|(`[:space:]])git[[:space:]]+(push|checkout|clean|branch|tag)[^|;&]*[[:space:]]-f[A-Za-z]*([[:space:]]|$)'
if [[ "$CMD" =~ $FORCE_F_RE ]]; then
  block "-f (on git ${BASH_REMATCH[2]})"
fi
```

- [ ] **Step 2: Parse-check the validator under host bash**

Run:

```bash
bash -n ~/.claude/skills/ship/lib/validate-git-cmd.sh && echo "PARSE OK"
```

Expected: `PARSE OK`. If the parser emits `syntax error in conditional expression: unexpected token ';'`, the pattern was inlined — re-check Step 1 used the **variable** form `$FORCE_F_RE`, not the literal regex inside `[[ =~ ]]`.

- [ ] **Step 3: Spot-check the patched lines**

Run:

```bash
sed -n '38,60p' ~/.claude/skills/ship/lib/validate-git-cmd.sh
```

Expected: the new block visible, including the `FORCE_F_RE=...` line and the `block "-f (on git ${BASH_REMATCH[2]})"` call. The original `block "-f"` call is gone.

---

## Task 6: Run full harness, confirm all cases green

**Files:**

- Run: `~/.claude/skills/ship/tests/run.sh`

- [ ] **Step 1: Run the harness**

Run:

```bash
bash ~/.claude/skills/ship/tests/run.sh
echo "exit=$?"
```

Expected last lines:

```
── ship lib tests ──
Passed: <N>
Failed: 0
exit=0
```

The `Failed: 0` and `exit=0` together are the green-bar contract.

- [ ] **Step 2: Manually verify the spec's acceptance-criteria contract**

Run each acceptance check directly (bypassing the harness) to confirm exit codes and stderr literals match the spec:

```bash
# AC #1: rm -f does NOT block.
echo '{"tool_name":"Bash","tool_input":{"command":"rm -f /tmp/foo"}}' | bash ~/.claude/skills/ship/lib/validate-git-cmd.sh ; echo "rm -f exit=$?"

# AC #3: git push -f DOES block, stderr mentions '-f (on git push)'.
echo '{"tool_name":"Bash","tool_input":{"command":"git push -f origin main"}}' | bash ~/.claude/skills/ship/lib/validate-git-cmd.sh 2>&1 >/dev/null
echo "git push -f exit=$?"

# AC #4-7: long-form regression guards.
for cmd in 'git push --force origin main' 'git push --force-with-lease' 'git commit --amend' 'git commit --no-verify'; do
  echo "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$cmd\"}}" | bash ~/.claude/skills/ship/lib/validate-git-cmd.sh 2>/dev/null
  echo "[$cmd] exit=$?"
done
```

Expected:

- `rm -f exit=0`
- `git push -f exit=2` with stderr containing `-f (on git push)`
- All four long-form cases `exit=2`

- [ ] **Step 3: Confirm shim is untouched**

Run:

```bash
ls -la ~/.claude/hooks/ship-guardrails.sh
md5sum ~/.claude/hooks/ship-guardrails.sh 2>/dev/null || md5 ~/.claude/hooks/ship-guardrails.sh
```

Expected: file exists and is 14 lines or thereabouts. The spec's AC #9 requires no shim change; this step is a sanity check, not a functional gate.

---

## Task 7: Capture forensic patch artifact

**Files:**

- Create: `$HOME/.claude/orchestrator/detached-changes/B11.patch`
- Read: `/tmp/cce77-validate-git-cmd.sh.orig`, `~/.claude/skills/ship/tests/validate-git-cmd.test.sh.orig`
- Read: `~/.claude/skills/ship/lib/validate-git-cmd.sh`, `~/.claude/skills/ship/tests/validate-git-cmd.test.sh`, `~/.claude/skills/ship/tests/run.sh`

- [ ] **Step 1: Ensure the destination directory exists**

Run:

```bash
mkdir -p "$HOME/.claude/orchestrator/detached-changes"
ls -ld "$HOME/.claude/orchestrator/detached-changes"
```

Expected: directory exists, is writable.

- [ ] **Step 2: Build the unified diff for the validator (post vs Task 1 snapshot)**

Run:

```bash
git diff --no-index --no-color /tmp/cce77-validate-git-cmd.sh.orig ~/.claude/skills/ship/lib/validate-git-cmd.sh > /tmp/cce77-validator.patch
echo "validator patch exit (1 means diff present, expected): $?"
wc -l /tmp/cce77-validator.patch
```

Expected: exit 1 (diff present), patch file is non-empty.

- [ ] **Step 3: Build the unified diff for the test file (post vs `.orig` baseline)**

Run:

```bash
git diff --no-index --no-color ~/.claude/skills/ship/tests/validate-git-cmd.test.sh.orig ~/.claude/skills/ship/tests/validate-git-cmd.test.sh > /tmp/cce77-tests.patch
echo "tests patch exit (1 means diff present, expected): $?"
wc -l /tmp/cce77-tests.patch
```

Expected: exit 1 (diff present), non-empty patch.

- [ ] **Step 4: Build the unified diff for `run.sh` if it was modified in Task 2**

Run:

```bash
# Snapshot the current run.sh against a re-derived baseline. If Task 2 added the
# helper, this captures it; if it did not (helper pre-existed), the diff is empty
# and that's fine.
if [[ -f /tmp/cce77-run.sh.orig ]]; then
  git diff --no-index --no-color /tmp/cce77-run.sh.orig ~/.claude/skills/ship/tests/run.sh > /tmp/cce77-run.patch || true
else
  : > /tmp/cce77-run.patch
fi
wc -l /tmp/cce77-run.patch
```

Note: Task 2 did not snapshot `run.sh` to `/tmp/cce77-run.sh.orig` because the orchestrator does not guarantee a clean baseline for the harness driver. If the helper was already present (Task 2 Step 1 saw it), this patch is empty; if not, the change is implicit in the validator patch's accompanying narrative and the orchestrator note. Accept either state.

- [ ] **Step 5: Concatenate the patches into the single artifact**

Run:

```bash
{
  echo "# CCE-77 — Narrow /ship guardrails -f token check to git subcommands"
  echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# Spec: docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md"
  echo "# Plan: docs/superpowers/plans/2026-06-04-cce77-ship-guardrails-fix.md"
  echo "#"
  echo "# Targets (all outside any git repo):"
  echo "#   ~/.claude/skills/ship/lib/validate-git-cmd.sh"
  echo "#   ~/.claude/skills/ship/tests/validate-git-cmd.test.sh"
  echo "#   ~/.claude/skills/ship/tests/run.sh  (helper added if missing)"
  echo "#"
  echo ""
  cat /tmp/cce77-validator.patch
  echo ""
  cat /tmp/cce77-tests.patch
  echo ""
  cat /tmp/cce77-run.patch
} > "$HOME/.claude/orchestrator/detached-changes/B11.patch"

echo "patch bytes: $(wc -c < "$HOME/.claude/orchestrator/detached-changes/B11.patch")"
echo "patch lines: $(wc -l < "$HOME/.claude/orchestrator/detached-changes/B11.patch")"
```

Expected: non-empty file with both the validator and tests diffs visible. Byte count > 1000 (the validator block alone is ~25 lines plus the test additions).

- [ ] **Step 6: Smoke-verify the patch artifact is well-formed**

Run:

```bash
head -20 "$HOME/.claude/orchestrator/detached-changes/B11.patch"
grep -c '^diff --git' "$HOME/.claude/orchestrator/detached-changes/B11.patch"
```

Expected: header comment lines visible up top, then `diff --git` markers. The grep count is ≥ 2 (validator + tests; possibly 3 if `run.sh` changed).

- [ ] **Step 7: Clean up snapshots**

Run:

```bash
rm -f /tmp/cce77-validate-git-cmd.sh.orig /tmp/cce77-validator.patch /tmp/cce77-tests.patch /tmp/cce77-run.patch /tmp/cce77-run.sh.orig
```

Expected: no errors. Snapshots are no longer needed once the artifact is on disk.

---

## Task 8: Final acceptance gate — re-run harness, summarize state

**Files:**

- Run: `~/.claude/skills/ship/tests/run.sh`

- [ ] **Step 1: Re-run the harness and summarize**

Run:

```bash
bash ~/.claude/skills/ship/tests/run.sh
```

Expected: `Failed: 0` and exit 0.

- [ ] **Step 2: Print acceptance summary**

Echo a one-line summary the orchestrator can parse:

Run:

```bash
echo "CCE-77 ACCEPTANCE: validator patched, $(grep -c '^# Case' ~/.claude/skills/ship/tests/validate-git-cmd.test.sh) test cases pass, artifact at $HOME/.claude/orchestrator/detached-changes/B11.patch"
```

Expected: single line printed; case count is ≥ 30 (Cases 1-30 enumerated).

---

## Self-review against the spec

This section is the writer's checklist, not an executable task. Confirmed before saving:

**Spec coverage:**

- Acceptance criteria #1 (`rm -f` passes) → Case 11 (existing) + Task 6 Step 2 manual check.
- Acceptance criteria #2 (`find -f` passes) → Case 13.
- Acceptance criteria #3 (`git push -f` blocks, stderr `-f (on git push)`) → Cases 16, 30 + Task 6 Step 2.
- Acceptance criteria #4-7 (long-form blocks regression-guarded) → Cases 2-6 (existing 14-32) + Task 6 Step 2.
- Acceptance criteria #8 (every block/pass case has a test) → Cases 11-30 enumerated in Task 3.
- Acceptance criteria #9 (shim unchanged) → Task 6 Step 3.
- Acceptance criteria #10 (no `unbound variable`, no `syntax error` on stderr) → Case 30 `assert_stderr_not_contains` calls.
- Acceptance criteria #11 (regex assigned to variable, `bash -n` precondition in harness) → Task 3 Step 2 inserts the precondition; Task 5 Step 1 uses `FORCE_F_RE=...` then `[[ "$CMD" =~ $FORCE_F_RE ]]`.

**Behavior matrix coverage:** every row in the spec's matrix maps to a test case in Cases 11-30 except the documented "known bypass" rows (`git -C ...` and `git -c ...`), which the spec explicitly marks out-of-scope.

**Placeholder scan:** no TBDs, no "implement later", every step has either an exact command + expected output, an exact edit, or a verbatim code block.

**Type consistency:** `FORCE_F_RE` is the only new variable name and is referenced consistently in Task 5. `assert_stderr_not_contains` signature `(stderr, needle, label)` matches between Task 2 (definition) and Task 3 (use). `BASH_REMATCH[2]` is the subcommand capture group — index 2 in the regex `(^|[...])git[[:space:]]+(push|...)...`, where group 1 is the leading-boundary char and group 2 is the subcommand. Verified by inspection.

**Constraint compliance:** no commits run; forensic patch lands at the exact path the orchestrator expects (`$HOME/.claude/orchestrator/detached-changes/B11.patch`); test runner invocation matches the orchestrator's documented command (`bash ~/.claude/skills/ship/tests/run.sh` — the test file itself is source-only).

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-04-cce77-ship-guardrails-fix.md`.

Execution mode is fixed by the orchestrator: **subagent-driven-development**. Each task above is a discrete dispatch unit with a clear pre/post state. Task ordering is strict (each task depends on the previous one's filesystem state). No parallelism within tasks; tasks themselves are sequential.

The orchestrator's B11 dispatcher should:

1. Spawn one subagent per task with the task's heading + steps as the brief.
2. After each task, run `bash ~/.claude/skills/ship/tests/run.sh` as a between-tasks gate (Task 4 and onward).
3. On Task 7 completion, attach the patch artifact path to the orchestrator's outbound report.
4. On Task 8 green-bar, mark B11 done and proceed to the next batch task.

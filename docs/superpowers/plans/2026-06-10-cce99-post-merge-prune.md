# CCE-99 Post-Merge Branch Prune Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After any `gh pr merge` in any Claude session, automatically delete local branches whose origin counterpart is gone — squash merges included, via full-SHA verification against the merged PR.

**Architecture:** A global PostToolUse hook (`~/.claude/hooks/post-merge-prune.sh`) detects `gh pr merge` commands and delegates to a self-verifying worker (`~/.claude/skills/ship/lib/prune-merged-branches.sh`) that sweeps `[gone]` branches: `git branch -d` first, then `git branch -D` only when a MERGED PR's `headRefOid` equals the local tip (full 40-character compare). Local-only, always exits 0, journals `pruned` entries.

**Tech Stack:** bash (macOS 3.2-compatible — newline-delimited strings, no array expansions under `set -u`), `jq`, `gh`, the ship skill's sourced-test harness (`tests/run.sh`).

**Spec:** `docs/superpowers/specs/2026-06-10-cce99-ship-post-merge-prune-design.md`

**Two critical context notes for the engineer:**

1. **`~/.claude` is NOT a git repo.** Tasks 1–7 create/modify user-global files that cannot be committed. The "run the full test suite" step at the end of each task replaces the commit checkpoint. Back up any _modified_ (not created) file first — the convention is a `.pre-cce99-backup` suffix. Only Task 8 commits anything (this repo's docs).
2. **Test files are `source`d into one shared shell** by `tests/run.sh` — they are NOT subprocesses. Helper-function and global-variable names must not collide with other `*.test.sh` files (existing names: `run_in_tmp_capture`, `run_with_mock_gh`). That's why everything here is prefixed `pmp_`.
3. **Never let a test invocation write the real journal.** Every worker invocation in tests sets `CLAUDE_PLUGIN_DATA` to a fixture-local dir. The worker resolves the journal as `${CLAUDE_PLUGIN_DATA:-$HOME/.claude}/ship/journal.jsonl`.

**File structure (whole feature):**

| File                                                          | Role                                                 |
| ------------------------------------------------------------- | ---------------------------------------------------- |
| `~/.claude/skills/ship/lib/prune-merged-branches.sh`          | Create — worker, all sweep logic                     |
| `~/.claude/skills/ship/tests/prune-merged-branches.test.sh`   | Create — test cases, built incrementally Tasks 1–5   |
| `~/.claude/hooks/post-merge-prune.sh`                         | Create — trigger, stdin-JSON filter + delegate       |
| `~/.claude/settings.json`                                     | Modify — append one PostToolUse entry (backup first) |
| `~/.claude/skills/ship/spokes/post-merge-prune.md`            | Create — contract documentation                      |
| `~/.claude/skills/ship/spokes/push-pr.md`                     | Modify — one pointer paragraph                       |
| `docs/superpowers/plans/2026-06-10-cce99-post-merge-prune.md` | This plan (already committed)                        |

---

### Task 1: Worker skeleton — silent no-ops (not-a-repo, clean repo)

**Files:**

- Create: `~/.claude/skills/ship/tests/prune-merged-branches.test.sh`
- Create: `~/.claude/skills/ship/lib/prune-merged-branches.sh`

- [ ] **Step 1: Write the failing tests**

Create `~/.claude/skills/ship/tests/prune-merged-branches.test.sh` with exactly:

```bash
# Tests for ~/.claude/skills/ship/lib/prune-merged-branches.sh (CCE-99)
# and ~/.claude/hooks/post-merge-prune.sh (Task 5 cases).
PMP_LIB="$DIR/../lib/prune-merged-branches.sh"
PMP_HOOK="$DIR/../../../hooks/post-merge-prune.sh"

# Local string-contains assert (prefixed: test files share one shell).
pmp_contains() {
  local haystack="$1" needle="$2" label="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    HARNESS_PASS=$((HARNESS_PASS+1))
  else
    echo "FAIL [$HARNESS_NAME] $label: '$needle' not in: '$haystack'"
    HARNESS_FAIL=$((HARNESS_FAIL+1))
  fi
}

# Fixture: bare origin + working clone with an initial main commit.
# Sets PMP_FIX (root temp dir) and PMP_WORK (the clone).
pmp_make_fixture() {
  PMP_FIX=$(mktemp -d -t cce99-fix.XXXXXX)
  git init --bare --quiet --initial-branch=main "$PMP_FIX/origin.git"
  git clone --quiet "$PMP_FIX/origin.git" "$PMP_FIX/work" 2>/dev/null
  PMP_WORK="$PMP_FIX/work"
  git -C "$PMP_WORK" config user.email cce99@test
  git -C "$PMP_WORK" config user.name cce99
  git -C "$PMP_WORK" commit --allow-empty -q -m init
  git -C "$PMP_WORK" push -q origin main
}

# Run the worker inside a dir, journal redirected into the fixture.
# Usage: pmp_run <dir> [extra worker args...]
pmp_run() {
  local dir="$1"; shift
  ( cd "$dir" && CLAUDE_PLUGIN_DATA="$PMP_FIX/data" bash "$PMP_LIB" "$@" 2>&1 )
}

# ── Case: not a git repo → silent exit 0 ──
PMP_FIX=$(mktemp -d -t cce99-fix.XXXXXX)
out=$(pmp_run "$PMP_FIX"); rc=$?
assert_exit "$rc" "0" "non-repo exit 0"
assert_eq "$out" "" "non-repo silent"
rm -rf "$PMP_FIX"

# ── Case: repo with no [gone] branches → silent, no journal ──
pmp_make_fixture
out=$(pmp_run "$PMP_WORK"); rc=$?
assert_exit "$rc" "0" "clean repo exit 0"
assert_eq "$out" "" "clean repo silent"
if [[ -e "$PMP_FIX/data/ship/journal.jsonl" ]]; then
  echo "FAIL [$HARNESS_NAME] clean repo: journal written on empty sweep"
  HARNESS_FAIL=$((HARNESS_FAIL+1))
else
  HARNESS_PASS=$((HARNESS_PASS+1))
fi
rm -rf "$PMP_FIX"
```

- [ ] **Step 2: Run the suite to verify the new cases fail**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: `Failed:` count > 0, with FAIL lines naming `prune-merged-branches` (the lib file doesn't exist, so `bash "$PMP_LIB"` exits non-zero).

- [ ] **Step 3: Write the worker skeleton**

Create `~/.claude/skills/ship/lib/prune-merged-branches.sh` with exactly:

```bash
#!/usr/bin/env bash
# prune-merged-branches.sh (CCE-99)
# Delete local branches whose origin counterpart is gone. Squash-merged
# branches are force-deleted only when a MERGED PR's headRefOid equals the
# local tip (full 40-char compare). Local-only: never pushes. Always exits 0
# — runs as a PostToolUse hook; a prune failure must never block the loop.
#
# Usage: prune-merged-branches.sh [--trigger-cmd "<original bash command>"]
# Run with cwd inside the target repo.
#
# Spec: engineering-docs-agent
#   docs/superpowers/specs/2026-06-10-cce99-ship-post-merge-prune-design.md
set -u

TRIGGER_CMD=""
if [[ "${1:-}" == "--trigger-cmd" ]]; then
  TRIGGER_CMD="${2:-}"
fi

# Not a git repo → silent no-op.
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

START_MS=$(($(date +%s) * 1000))

# Refresh remote-tracking refs so just-deleted remote branches show [gone].
if ! git fetch --prune --quiet 2>/dev/null; then
  echo "post-merge-prune: git fetch --prune failed (offline?) — skipping sweep"
  exit 0
fi

CURRENT=$(git branch --show-current)  # empty on detached HEAD

# Newline-delimited accumulators (macOS bash 3.2: avoid arrays under set -u).
DELETED=""   # lines: "branch@shortsha"
SKIPPED=""   # lines: "branch:reason" (reason may itself contain ': ')

# Sweep loop lands in Task 2.

# Nothing happened → stay silent (no report, no journal).
[[ -z "$DELETED" && -z "$SKIPPED" ]] && exit 0

exit 0
```

Then: `chmod +x ~/.claude/skills/ship/lib/prune-merged-branches.sh`

- [ ] **Step 4: Run the suite to verify it passes**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: `Failed: 0` (all pre-existing cases plus the two new ones pass; `TRIGGER_CMD`/`START_MS`/`CURRENT` are unused so far — that's fine under `set -u`, they're assigned, not referenced).

---

### Task 2: Sweep loop — `-d` deletes, checked-out and protected skips

**Files:**

- Modify: `~/.claude/skills/ship/tests/prune-merged-branches.test.sh` (append)
- Modify: `~/.claude/skills/ship/lib/prune-merged-branches.sh`

- [ ] **Step 1: Append the failing tests**

Append to `prune-merged-branches.test.sh`:

```bash
# ── Case: merge-commit branch, remote deleted → pruned via -d ──
pmp_make_fixture
git -C "$PMP_WORK" checkout -q -b feat-mc
git -C "$PMP_WORK" commit --allow-empty -q -m change
git -C "$PMP_WORK" push -q -u origin feat-mc
git -C "$PMP_WORK" checkout -q main
git -C "$PMP_WORK" merge -q --no-ff feat-mc -m "merge feat-mc"
git -C "$PMP_WORK" push -q origin main
git -C "$PMP_WORK" push -q origin --delete feat-mc
out=$(pmp_run "$PMP_WORK"); rc=$?
assert_exit "$rc" "0" "merge-commit exit 0"
pmp_contains "$out" "deleted feat-mc@" "merge-commit reported deleted"
git -C "$PMP_WORK" rev-parse --verify -q feat-mc >/dev/null 2>&1; gone=$?
assert_exit "$gone" "1" "merge-commit branch actually deleted"
rm -rf "$PMP_FIX"

# ── Case: candidate branch is checked out → skipped ──
pmp_make_fixture
git -C "$PMP_WORK" checkout -q -b feat-co
git -C "$PMP_WORK" commit --allow-empty -q -m change
git -C "$PMP_WORK" push -q -u origin feat-co
git -C "$PMP_WORK" push -q origin --delete feat-co
out=$(pmp_run "$PMP_WORK"); rc=$?
assert_exit "$rc" "0" "checked-out exit 0"
pmp_contains "$out" "skipped feat-co (checked-out)" "checked-out reported skipped"
git -C "$PMP_WORK" rev-parse --verify -q feat-co >/dev/null 2>&1; still=$?
assert_exit "$still" "0" "checked-out branch still exists"
rm -rf "$PMP_FIX"
```

- [ ] **Step 2: Run the suite to verify the new cases fail**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: FAIL lines for "merge-commit reported deleted", "merge-commit branch actually deleted", "checked-out reported skipped" (the worker has no sweep loop yet, so output is empty and the branch survives).

- [ ] **Step 3: Implement the sweep loop**

In `prune-merged-branches.sh`, replace the line `# Sweep loop lands in Task 2.` with:

```bash
while IFS=' ' read -r BRANCH TRACK; do
  [[ "$TRACK" == "[gone]" ]] || continue

  if [[ "$BRANCH" == "$CURRENT" ]]; then
    SKIPPED+="$BRANCH:checked-out"$'\n'; continue
  fi
  case "$BRANCH" in
    main|master|develop)
      SKIPPED+="$BRANCH:protected"$'\n'; continue ;;
  esac

  TIP=$(git rev-parse "$BRANCH" 2>/dev/null) || {
    SKIPPED+="$BRANCH:unresolvable"$'\n'; continue
  }

  if git branch -d "$BRANCH" >/dev/null 2>&1; then
    DELETED+="$BRANCH@${TIP:0:8}"$'\n'; continue
  fi

  # -d refused → squash-merge candidate. Verification lands in Task 3.
  SKIPPED+="$BRANCH:unverified: tip not on a merged PR"$'\n'
done < <(git for-each-ref --format='%(refname:short) %(upstream:track)' refs/heads)
```

And replace the final block

```bash
# Nothing happened → stay silent (no report, no journal).
[[ -z "$DELETED" && -z "$SKIPPED" ]] && exit 0

exit 0
```

with:

```bash
# Nothing happened → stay silent (no report, no journal).
[[ -z "$DELETED" && -z "$SKIPPED" ]] && exit 0

printf '%s' "$DELETED" | while IFS= read -r LINE; do
  [[ -n "$LINE" ]] && echo "post-merge-prune: deleted $LINE"
done
printf '%s' "$SKIPPED" | while IFS= read -r LINE; do
  [[ -n "$LINE" ]] && echo "post-merge-prune: skipped ${LINE%%:*} (${LINE#*:})"
done

exit 0
```

Note on the skip-report parsing: `${LINE%%:*}` takes the branch (everything before the FIRST colon), `${LINE#*:}` the reason (everything after it) — reasons like `unverified: gh unavailable` keep their internal colon.

- [ ] **Step 4: Run the suite to verify it passes**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: `Failed: 0`. (The `%(upstream:track)` format prints `[gone]` for deleted upstreams and empty otherwise; branches without upstream produce an empty `TRACK` and are skipped by the `[[ "$TRACK" == "[gone]" ]]` guard.)

---

### Task 3: Squash-merge verification via `gh` — full-SHA compare

**Files:**

- Modify: `~/.claude/skills/ship/tests/prune-merged-branches.test.sh` (append)
- Modify: `~/.claude/skills/ship/lib/prune-merged-branches.sh`

- [ ] **Step 1: Append the failing tests**

Append to `prune-merged-branches.test.sh`:

```bash
# Squash-merge fixture: branch pushed, NOT merged into main (a separate
# "squash" commit lands on main instead), remote branch deleted.
# Sets PMP_TIP to the branch tip SHA. Caller provides the gh mock body.
pmp_make_squash_fixture() {
  pmp_make_fixture
  git -C "$PMP_WORK" checkout -q -b feat-sq
  git -C "$PMP_WORK" commit --allow-empty -q -m change
  git -C "$PMP_WORK" push -q -u origin feat-sq
  PMP_TIP=$(git -C "$PMP_WORK" rev-parse feat-sq)
  git -C "$PMP_WORK" checkout -q main
  git -C "$PMP_WORK" commit --allow-empty -q -m "squash equivalent"
  git -C "$PMP_WORK" push -q origin main
  git -C "$PMP_WORK" push -q origin --delete feat-sq
}

# Run the worker with a mock gh injected via PATH.
# Usage: pmp_run_mock_gh <gh-script-body> [worker args...]
pmp_run_mock_gh() {
  local body="$1"; shift
  local mockdir; mockdir=$(mktemp -d -t cce99-gh.XXXXXX)
  printf '#!/usr/bin/env bash\n%s\n' "$body" > "$mockdir/gh"
  chmod +x "$mockdir/gh"
  ( cd "$PMP_WORK" && CLAUDE_PLUGIN_DATA="$PMP_FIX/data" \
      PATH="$mockdir:$PATH" bash "$PMP_LIB" "$@" 2>&1 )
  local rc=$?
  rm -rf "$mockdir"
  return $rc
}

# Note: the gh-fail case below exercises the same skip-reason branch as a
# truly absent gh ('unverified: gh unavailable') — the worker treats
# command-not-found and API failure identically, and removing gh from PATH
# in a test would also remove git. One mock covers both.

# ── Case: squash-merged, gh confirms tip → pruned via -D ──
pmp_make_squash_fixture
out=$(pmp_run_mock_gh "echo $PMP_TIP"); rc=$?
assert_exit "$rc" "0" "squash-verified exit 0"
pmp_contains "$out" "deleted feat-sq@" "squash-verified reported deleted"
git -C "$PMP_WORK" rev-parse --verify -q feat-sq >/dev/null 2>&1; gone=$?
assert_exit "$gone" "1" "squash-verified branch actually deleted"
rm -rf "$PMP_FIX"

# ── Case: gh returns a DIFFERENT sha → skipped, branch survives ──
pmp_make_squash_fixture
out=$(pmp_run_mock_gh "echo 0000000000000000000000000000000000000000"); rc=$?
assert_exit "$rc" "0" "sha-mismatch exit 0"
pmp_contains "$out" "skipped feat-sq (unverified: tip not on a merged PR)" "sha-mismatch reported"
git -C "$PMP_WORK" rev-parse --verify -q feat-sq >/dev/null 2>&1; still=$?
assert_exit "$still" "0" "sha-mismatch branch survives"
rm -rf "$PMP_FIX"

# ── Case: gh call fails → skipped with 'gh unavailable', branch survives ──
pmp_make_squash_fixture
out=$(pmp_run_mock_gh "echo 'gh: network error' >&2; exit 1"); rc=$?
assert_exit "$rc" "0" "gh-fail exit 0"
pmp_contains "$out" "skipped feat-sq (unverified: gh unavailable)" "gh-fail reported"
git -C "$PMP_WORK" rev-parse --verify -q feat-sq >/dev/null 2>&1; still=$?
assert_exit "$still" "0" "gh-fail branch survives"
rm -rf "$PMP_FIX"
```

- [ ] **Step 2: Run the suite to verify the new cases fail**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: FAIL on "squash-verified reported deleted" and "squash-verified branch actually deleted" (worker currently skips every `-d` refusal). The mismatch and gh-fail cases may already pass for the wrong reason (everything is skipped) — that's expected at this step; the deleted-case failures are the discriminator.

- [ ] **Step 3: Implement verification**

In `prune-merged-branches.sh`, replace:

```bash
  # -d refused → squash-merge candidate. Verification lands in Task 3.
  SKIPPED+="$BRANCH:unverified: tip not on a merged PR"$'\n'
```

with:

```bash
  # -d refused → squash-merge candidate. Force-delete ONLY when a MERGED
  # PR's headRefOid equals the local tip. Full 40-char equality — never a
  # prefix compare (the 2026-06-10 manual sweep's guard failed closed on
  # exactly that mismatch).
  if ! command -v gh >/dev/null 2>&1; then
    SKIPPED+="$BRANCH:unverified: gh unavailable"$'\n'; continue
  fi
  if ! PR_HEADS=$(gh pr list --head "$BRANCH" --state merged \
      --json headRefOid --jq '.[].headRefOid' 2>/dev/null); then
    SKIPPED+="$BRANCH:unverified: gh unavailable"$'\n'; continue
  fi
  VERIFIED=false
  while IFS= read -r OID; do
    [[ -n "$OID" && "$OID" == "$TIP" ]] && VERIFIED=true
  done <<< "$PR_HEADS"
  if [[ "$VERIFIED" == true ]] && git branch -D "$BRANCH" >/dev/null 2>&1; then
    DELETED+="$BRANCH@${TIP:0:8}"$'\n'
  elif [[ "$VERIFIED" == true ]]; then
    SKIPPED+="$BRANCH:delete-failed"$'\n'
  else
    SKIPPED+="$BRANCH:unverified: tip not on a merged PR"$'\n'
  fi
```

- [ ] **Step 4: Run the suite to verify it passes**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: `Failed: 0`.

---

### Task 4: Journal entry + `--delete-branch` advisory

**Files:**

- Modify: `~/.claude/skills/ship/tests/prune-merged-branches.test.sh` (append)
- Modify: `~/.claude/skills/ship/lib/prune-merged-branches.sh`

- [ ] **Step 1: Append the failing tests**

Append to `prune-merged-branches.test.sh`:

```bash
# ── Case: journal entry written on a real prune; advisory tip shown ──
pmp_make_squash_fixture
out=$(pmp_run_mock_gh "echo $PMP_TIP" --trigger-cmd "gh pr merge 7 --squash")
pmp_contains "$out" "deleted feat-sq@" "journal-case pruned"
pmp_contains "$out" "tip: 'gh pr merge --delete-branch'" "advisory tip shown"
PMP_JOURNAL="$PMP_FIX/data/ship/journal.jsonl"
if [[ -f "$PMP_JOURNAL" ]]; then
  HARNESS_PASS=$((HARNESS_PASS+1))
else
  echo "FAIL [$HARNESS_NAME] journal file missing: $PMP_JOURNAL"
  HARNESS_FAIL=$((HARNESS_FAIL+1))
fi
outcome=$(jq -r '.outcome' "$PMP_JOURNAL" 2>/dev/null | tail -1)
assert_eq "$outcome" "pruned" "journal outcome field"
ndeleted=$(jq -r '.deleted | length' "$PMP_JOURNAL" 2>/dev/null | tail -1)
assert_eq "$ndeleted" "1" "journal deleted count"
rm -rf "$PMP_FIX"

# ── Case: advisory NOT shown when --delete-branch was used ──
pmp_make_squash_fixture
out=$(pmp_run_mock_gh "echo $PMP_TIP" --trigger-cmd "gh pr merge 7 --squash --delete-branch")
if [[ "$out" == *"tip: 'gh pr merge --delete-branch'"* ]]; then
  echo "FAIL [$HARNESS_NAME] advisory shown despite --delete-branch"
  HARNESS_FAIL=$((HARNESS_FAIL+1))
else
  HARNESS_PASS=$((HARNESS_PASS+1))
fi
rm -rf "$PMP_FIX"
```

- [ ] **Step 2: Run the suite to verify the new cases fail**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: FAIL on "advisory tip shown", "journal outcome field", "journal deleted count" (and the journal-file existence check).

- [ ] **Step 3: Implement journal + advisory**

In `prune-merged-branches.sh`, replace the final `exit 0` (after the two report loops) with:

```bash
if [[ "$TRIGGER_CMD" == *"gh pr merge"* && "$TRIGGER_CMD" != *"--delete-branch"* ]]; then
  echo "post-merge-prune: tip: 'gh pr merge --delete-branch' also removes the remote branch"
fi

# Journal (best-effort; same path the /ship lifecycle uses).
if command -v jq >/dev/null 2>&1; then
  JOURNAL_PATH="${CLAUDE_PLUGIN_DATA:-$HOME/.claude}/ship/journal.jsonl"
  if mkdir -p "$(dirname "$JOURNAL_PATH")" 2>/dev/null; then
    END_MS=$(($(date +%s) * 1000))
    DEL_JSON=$(printf '%s' "$DELETED" | jq -R 'select(length>0)' | jq -s '.')
    SKIP_JSON=$(printf '%s' "$SKIPPED" \
      | jq -R 'select(length>0) | capture("(?<branch>[^:]+):(?<reason>.*)")' \
      | jq -s '.')
    jq -cn \
      --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --arg repo "$(basename "$(git rev-parse --show-toplevel)")" \
      --argjson deleted "$DEL_JSON" \
      --argjson skipped "$SKIP_JSON" \
      --argjson duration_ms "$((END_MS - START_MS))" \
      '{ts: $ts, outcome: "pruned", repo: $repo, deleted: $deleted,
        skipped: $skipped, duration_ms: $duration_ms}' \
      >> "$JOURNAL_PATH" 2>/dev/null
  fi
fi

exit 0
```

- [ ] **Step 4: Run the suite to verify it passes**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: `Failed: 0`. (Empty `printf '%s' ""` piped through `jq -R | jq -s` yields `[]`, so an all-skipped sweep journals `"deleted": []` cleanly.)

---

### Task 5: Trigger script — stdin filter + delegate

**Files:**

- Modify: `~/.claude/skills/ship/tests/prune-merged-branches.test.sh` (append)
- Create: `~/.claude/hooks/post-merge-prune.sh`

- [ ] **Step 1: Append the failing tests**

Append to `prune-merged-branches.test.sh`:

```bash
# ── Trigger cases: worker stubbed via SHIP_PRUNE_WORKER (DI seam) ──
PMP_TFIX=$(mktemp -d -t cce99-trig.XXXXXX)
cat > "$PMP_TFIX/stub-worker.sh" <<'EOF'
#!/usr/bin/env bash
pwd > "${PMP_MARKER:?}"
echo "args:$*" >> "${PMP_MARKER:?}"
EOF
chmod +x "$PMP_TFIX/stub-worker.sh"

# Non-merge command → worker NOT invoked.
printf '{"tool_input":{"command":"ls -la"},"cwd":"%s"}' "$PMP_TFIX" \
  | PMP_MARKER="$PMP_TFIX/marker" SHIP_PRUNE_WORKER="$PMP_TFIX/stub-worker.sh" \
    bash "$PMP_HOOK"; rc=$?
assert_exit "$rc" "0" "trigger non-merge exit 0"
if [[ -e "$PMP_TFIX/marker" ]]; then
  echo "FAIL [$HARNESS_NAME] trigger fired on non-merge command"
  HARNESS_FAIL=$((HARNESS_FAIL+1))
else
  HARNESS_PASS=$((HARNESS_PASS+1))
fi

# Merge command → worker invoked in the JSON's cwd, command passed through.
printf '{"tool_input":{"command":"gh pr merge 12 --squash"},"cwd":"%s"}' "$PMP_TFIX" \
  | PMP_MARKER="$PMP_TFIX/marker" SHIP_PRUNE_WORKER="$PMP_TFIX/stub-worker.sh" \
    bash "$PMP_HOOK"; rc=$?
assert_exit "$rc" "0" "trigger merge exit 0"
if [[ -e "$PMP_TFIX/marker" ]]; then
  HARNESS_PASS=$((HARNESS_PASS+1))
else
  echo "FAIL [$HARNESS_NAME] trigger did not fire on merge command"
  HARNESS_FAIL=$((HARNESS_FAIL+1))
fi
marker_dir=$(head -1 "$PMP_TFIX/marker" 2>/dev/null)
pmp_expected_dir=$(cd "$PMP_TFIX" && pwd -P)
marker_dir_resolved=$(cd "$marker_dir" 2>/dev/null && pwd -P)
assert_eq "$marker_dir_resolved" "$pmp_expected_dir" "trigger cd'd to JSON cwd"
pmp_contains "$(cat "$PMP_TFIX/marker" 2>/dev/null)" "args:--trigger-cmd gh pr merge 12 --squash" "trigger passed command through"

rm -rf "$PMP_TFIX"
```

- [ ] **Step 2: Run the suite to verify the new cases fail**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: FAIL lines for the trigger cases (`$PMP_HOOK` does not exist yet).

- [ ] **Step 3: Write the trigger**

Create `~/.claude/hooks/post-merge-prune.sh` with exactly:

```bash
#!/usr/bin/env bash
# post-merge-prune.sh (CCE-99)
# Global PostToolUse hook on Bash. Fires after any Bash tool call whose
# command contains 'gh pr merge'; delegates to the ship lib worker that
# prunes local branches whose origin counterpart is gone.
# Deliberately NOT gated on /tmp/.ship-active — covering non-/ship merges
# is the point (all 7 stale branches in the 2026-06-10 sweep came from
# merges outside /ship).
# Always exits 0 — never blocks the session loop. False-positive fires
# (the substring inside an echoed string) are harmless: the worker is
# self-verifying and idempotent.
set -u

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
[[ "$CMD" == *"gh pr merge"* ]] || exit 0

CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[[ -n "$CWD" && -d "$CWD" ]] || exit 0
cd "$CWD" || exit 0

# SHIP_PRUNE_WORKER is a test seam; real path is the ship lib worker.
WORKER="${SHIP_PRUNE_WORKER:-$HOME/.claude/skills/ship/lib/prune-merged-branches.sh}"
[[ -f "$WORKER" ]] || exit 0
exec bash "$WORKER" --trigger-cmd "$CMD"
```

Then: `chmod +x ~/.claude/hooks/post-merge-prune.sh`

- [ ] **Step 4: Run the suite to verify it passes**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: `Failed: 0`.

---

### Task 6: Register the hook in settings.json

**Files:**

- Modify: `~/.claude/settings.json` (backup first)

- [ ] **Step 1: Back up**

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.pre-cce99-backup
```

- [ ] **Step 2: Append the PostToolUse entry (idempotent)**

```bash
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path.home() / ".claude" / "settings.json"
d = json.loads(p.read_text())
cmd = "bash ~/.claude/hooks/post-merge-prune.sh"
post = d.setdefault("hooks", {}).setdefault("PostToolUse", [])
already = any(h.get("command") == cmd for e in post for h in e.get("hooks", []))
if not already:
    post.append({"matcher": "Bash",
                 "hooks": [{"type": "command", "command": cmd, "timeout": 60}]})
    p.write_text(json.dumps(d, indent=2) + "\n")
print("registered" if not already else "already registered")
EOF
```

Expected output: `registered`

- [ ] **Step 3: Verify the file is valid and the entry landed**

```bash
python3 -c "
import json, pathlib
d = json.loads((pathlib.Path.home()/'.claude'/'settings.json').read_text())
entries = [h['command'] for e in d['hooks']['PostToolUse'] for h in e['hooks']]
assert 'bash ~/.claude/hooks/post-merge-prune.sh' in entries, entries
print('OK:', entries)
"
```

Expected: `OK: [...]` listing the existing format/lint hooks plus the new one.

**Note:** hooks load at session start. The running session will NOT fire this hook; live verification happens in a fresh session (Task 8, step 3).

---

### Task 7: Documentation — new spoke + push-pr pointer

**Files:**

- Create: `~/.claude/skills/ship/spokes/post-merge-prune.md`
- Modify: `~/.claude/skills/ship/spokes/push-pr.md` (append one paragraph to the last section)

- [ ] **Step 1: Write the spoke**

Create `~/.claude/skills/ship/spokes/post-merge-prune.md` with exactly:

```markdown
# Post-merge prune (global hook — NOT a /ship stage)

A global PostToolUse hook fires after any Bash tool call containing
`gh pr merge` — every Claude session, every repo, /ship or not — and
deletes local branches whose origin counterpart is gone. Squash-merged
branches are force-deleted only when a MERGED PR's `headRefOid` equals
the local tip (full 40-character compare; never a prefix). Local-only:
never pushes, never deletes remote branches. CCE-99.

## Pieces

| Piece   | Path                                                                                                        |
| ------- | ----------------------------------------------------------------------------------------------------------- |
| Trigger | `~/.claude/hooks/post-merge-prune.sh` (PostToolUse, matcher `Bash`, timeout 60 — `~/.claude/settings.json`) |
| Worker  | `~/.claude/skills/ship/lib/prune-merged-branches.sh`                                                        |
| Tests   | `~/.claude/skills/ship/tests/prune-merged-branches.test.sh` (via `tests/run.sh`)                            |

## Behavior

`git fetch --prune`, then per `[gone]` branch: skip if checked out or
protected (`main`/`master`/`develop`); try `git branch -d`; if refused,
verify against `gh pr list --head <branch> --state merged` and `-D` on
exact tip match; otherwise skip with a reason. Skips and deletions are
reported to hook stdout. If the triggering merge lacked
`--delete-branch`, a one-line tip suggests it. Always exits 0; degraded
environments (no repo, offline, no `gh`, no `jq`) no-op or safe-skip —
never block.

## Journal

When the sweep deleted or skipped anything, one line is appended to the
ship journal (`${CLAUDE_PLUGIN_DATA:-$HOME/.claude}/ship/journal.jsonl`):

    {"ts": "...", "outcome": "pruned", "repo": "...",
     "deleted": ["branch@shortsha"],
     "skipped": [{"branch": "...", "reason": "..."}],
     "duration_ms": 2300}

Query: `jq 'select(.outcome == "pruned")' journal.jsonl` — third entry
shape alongside `shipped` and `halted`.

## Rollback

Remove the PostToolUse entry from `~/.claude/settings.json` (backup at
`settings.json.pre-cce99-backup`). Both scripts are inert without it.

## Spec

engineering-docs-agent
`docs/superpowers/specs/2026-06-10-cce99-ship-post-merge-prune-design.md`
```

- [ ] **Step 2: Append the pointer to push-pr.md**

Append to the END of `~/.claude/skills/ship/spokes/push-pr.md` (after the CCE-97 paragraph):

```markdown
After the merge lands, the global post-merge-prune hook sweeps local `[gone]` branches automatically (squash merges verified against the PR's head SHA) — no manual `git branch -d` needed. See `@spokes/post-merge-prune.md`. CCE-99.
```

- [ ] **Step 3: Verify the spoke reference resolves**

```bash
ls ~/.claude/skills/ship/spokes/post-merge-prune.md && \
  grep -c "post-merge-prune" ~/.claude/skills/ship/spokes/push-pr.md
```

Expected: the path, then `1`.

---

### Task 8: Final verification — suite, repo tests, live fire

**Files:**

- None created; this task verifies and ships.

- [ ] **Step 1: Full ship suite green**

Run: `bash ~/.claude/skills/ship/tests/run.sh`
Expected: `Failed: 0`.

- [ ] **Step 2: Repo-side commit + PR**

The spec (already committed) and this plan ship from branch `feat/CCE-99-ship-post-merge-prune`:

```bash
cd /Users/theo/Projects/engineering-docs-agent
# The plan may already be committed; only commit if it is staged-new.
git add docs/superpowers/plans/2026-06-10-cce99-post-merge-prune.md
git diff --cached --quiet || \
  git commit -m "docs(CCE-99): implementation plan — post-merge prune hook"
git push -u origin feat/CCE-99-ship-post-merge-prune
gh pr create --base main \
  --title "docs(CCE-99): post-merge local branch prune — spec + plan (user-global implementation)" \
  --body "$(cat <<'EOF'
## Summary

- Spec + implementation plan for CCE-99: a global PostToolUse hook on `gh pr merge` that prunes local `[gone]` branches, with full-SHA verification before force-deleting squash-merged branches.
- The implementation itself is user-global (`~/.claude/` — ship skill lib/tests, hook script, settings registration); this PR tracks the design artifacts.

## Test plan

- [ ] `bash ~/.claude/skills/ship/tests/run.sh` green (user-global suite)
- [ ] Reviewed rendered markdown

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Live fire — merging THIS PR is the verification**

Hooks load at session start, so this runs in a NEW session (or after the operator reloads settings):

1. In a fresh Claude session in this repo, merge the PR: `gh pr merge <N> --squash --delete-branch`.
2. Expected hook output in that session: `post-merge-prune: deleted feat/CCE-99-ship-post-merge-prune@<sha>` (the `--delete-branch` flag removes the remote; the hook's sweep — fired by the merge command — prunes the local).
3. Confirm: `git branch -vv` no longer lists the branch, and `jq 'select(.outcome == "pruned")' ~/.claude/ship/journal.jsonl | tail -1` shows the entry.
4. The PR title carries `CCE-99`, so the merge auto-transitions the ticket to Done (`jira-transition.yml`) — correct, because by then the implementation is live and verified. (Spec "Sequencing constraint" satisfied: implementation precedes the merge.)

If step 2 shows no hook output: check registration (`Task 6 Step 3` command), confirm the session started AFTER registration, and run the worker manually (`bash ~/.claude/skills/ship/lib/prune-merged-branches.sh`) to separate worker bugs from trigger bugs.

```

```

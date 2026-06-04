# CCE-77 / CCE-80 Cycle Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land CCE-84, CCE-85, CCE-87, CCE-88 as a coherent hygiene batch — one PR (CCE-85+87) + one admin call (CCE-84) + one user-home edit (CCE-88) — with comprehensive TDD where executable behavior changes, lint/grep verification for config/admin work, and 3-agent validation gates pre-execution and post-implementation.

**Architecture:** Three venues; see `docs/superpowers/specs/2026-06-04-cce77-cycle-hygiene-design.md` §Components. One git PR in `theoju/engineering-docs-agent`; one admin `gh api` call against the same repo; one direct edit of `~/.claude/skills/ship/lib/validate-git-cmd.sh` (which is not git-tracked).

**Tech Stack:** Python (pytest for CCE-87), YAML (CCE-85), bash 3.2.57-compatible regex (CCE-88), GitHub REST API (CCE-84).

---

## File Structure

| Component | File                                                                                     | Action                                                                           | LOC delta |
| --------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | --------- |
| A         | `/Users/theo/Projects/engineering-docs-agent/.github/workflows/docs.yml`                 | Modify: add 2 negation patterns to each of `push.paths` and `pull_request.paths` | +4, -0    |
| A         | `/Users/theo/Projects/engineering-docs-agent/tests/ci/test_docstring_flag_value_lint.py` | NEW                                                                              | +~80      |
| A         | `/Users/theo/Projects/engineering-docs-agent/tests/ci/fixtures/regression_docstring.py`  | NEW (test fixture)                                                               | +~15      |
| B         | (no file) — `gh api -X PUT repos/theoju/engineering-docs-agent/branches/main/protection` | Admin call                                                                       | —         |
| C         | `/Users/theo/.claude/skills/ship/lib/validate-git-cmd.sh`                                | Modify: replace lines 39-48 with variable-assigned regex                         | +~12, -10 |
| C         | `/Users/theo/.claude/skills/ship/tests/validate-git-cmd.test.sh`                         | Modify: append 10 new test cases                                                 | +~50, -0  |
| C         | `/Users/theo/.claude/skills/ship/.changelog/2026-06-04-cce-88.diff`                      | NEW (commit-equivalent record)                                                   | +~30      |

---

## Phase 0 — Pre-execution plan validation (3-agent gate)

Three independent agents validate this plan against the spec BEFORE any task starts. All three must return APPROVED (or DONE_WITH_CONCERNS the orchestrator can resolve inline) before Task 1.

- [ ] **Step 0.1: Spec-coverage agent** — verify each spec goal maps to a plan task; each acceptance criterion has a verification step; the regex prescribed in CCE-88 is referenced verbatim.
- [ ] **Step 0.2: Completeness agent** — placeholder scan; command-completeness scan; verify all `gh api` commands are runnable as-written; verify all `bash` test commands include the full case body, not "similar to existing."
- [ ] **Step 0.3: Scope agent** — flag scope creep (no extra files), scope-shedding (no missed acceptance criteria), and proportionality of the 3-agent gates given the per-component small size.

Orchestrator parallelizes Steps 0.1–0.3 in a single message with three Agent tool calls.

---

## Component A — CCE-85 + CCE-87 PR

**Repo:** `/Users/theo/Projects/engineering-docs-agent`
**Branch:** `chore/cce-77-80-hygiene-cce-85-87` (already created with the spec)

### Task A.1 — CCE-87 TDD: write the lint test + synthetic regression fixture

- [ ] **Step A.1.1: Create the regression fixture (the file the test should FAIL on)**

File: `/Users/theo/Projects/engineering-docs-agent/tests/ci/fixtures/regression_docstring.py`

```python
"""Regression fixture for CCE-87.

This module exists ONLY to be read by test_docstring_flag_value_lint.py
as a synthetic negative-path input. It must contain --FLAG VALUE shapes
in the module docstring OUTSIDE any fenced code block, so the lint
correctly detects them as the CCE-80 class of mkdocs-autorefs trap.

Usage: do not import. Treated as a data file by the test.

  --bar BAZ
  [--qux QUUX]
"""

PLACEHOLDER = True  # importable but no-op so static analysis doesn't object
```

The two `--FLAG VALUE` shapes are inside the docstring but OUTSIDE any backticks or `::` fence. The lint must detect both.

- [ ] **Step A.1.2: Create the test (RED on fixture, GREEN on scripts/\*.py)**

File: `/Users/theo/Projects/engineering-docs-agent/tests/ci/test_docstring_flag_value_lint.py`

````python
"""CCE-87: defensive test that fails when scripts/*.py docstrings carry
--FLAG VALUE shapes outside fenced/inline code blocks. Prevents the
CCE-80 class of mkdocs-autorefs WARNING-on-strict-build regression.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

PATTERN_BARE = re.compile(r"^\s+--[a-z][a-z_-]+\s+[A-Z][A-Z_]+", re.MULTILINE)
PATTERN_BRACKETED = re.compile(r"\[--[a-z][a-z_-]+\s+[A-Z][A-Z_]+\]")


def _strip_code_regions(docstring: str) -> str:
    """Remove regions that are legitimately allowed to contain --FLAG VALUE
    shapes: triple-backtick fences, single-backtick inline code, and
    reST-style `Name::` literal blocks (indented blocks following a `::`
    line — the post-CCE-80 wrapping idiom)."""
    # Triple-backtick fences (greedy match across newlines).
    s = re.sub(r"```.*?```", "", docstring, flags=re.DOTALL)
    # Inline backticks (single line).
    s = re.sub(r"`[^`\n]+`", "", s)
    # reST `Name::` literal blocks: from a `::` line through the end of the
    # indented block (until a non-indented or blank-then-non-indented line).
    s = re.sub(
        r"^\S.*::\s*\n(?:[ \t]+.*\n?)+",
        "",
        s,
        flags=re.MULTILINE,
    )
    return s


def _extract_docstrings(py_path: Path) -> list[str]:
    """Return all docstrings (module + each function/class) from py_path."""
    tree = ast.parse(py_path.read_text())
    out: list[str] = []
    mod_doc = ast.get_docstring(tree)
    if mod_doc:
        out.append(mod_doc)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node)
            if d:
                out.append(d)
    return out


def _lint_one(py_path: Path) -> list[str]:
    """Return list of offending lines (--FLAG VALUE outside code) for py_path."""
    findings: list[str] = []
    for doc in _extract_docstrings(py_path):
        stripped = _strip_code_regions(doc)
        for m in PATTERN_BARE.finditer(stripped):
            findings.append(f"bare:{m.group(0).strip()}")
        for m in PATTERN_BRACKETED.finditer(stripped):
            findings.append(f"bracketed:{m.group(0)}")
    return findings


@pytest.mark.parametrize("py_file", sorted(SCRIPTS_DIR.glob("*.py")))
def test_no_unwrapped_flag_value_in_docstrings(py_file: Path) -> None:
    """CCE-87: scripts/*.py docstrings must not carry --FLAG VALUE shapes
    outside fenced/inline code blocks. mkdocs-autorefs treats them as
    broken cross-refs and fails --strict builds."""
    findings = _lint_one(py_file)
    assert findings == [], (
        f"{py_file.name} has unwrapped --FLAG VALUE shapes in a docstring: "
        f"{findings}. Wrap in `inline backticks`, ```triple-backtick fence```, "
        f"or a reST `Usage::` literal block (see CCE-80 fix)."
    )


def test_fixture_triggers_lint() -> None:
    """CCE-87 self-check: the synthetic regression fixture MUST trigger the
    lint. If this fails, the lint stopped detecting the class of bug it was
    written to catch — fix the lint or the fixture, not the assertion."""
    fixture = FIXTURES_DIR / "regression_docstring.py"
    findings = _lint_one(fixture)
    assert any(f.startswith("bare:") for f in findings), (
        f"fixture {fixture.name} should trigger the bare-form pattern; "
        f"findings: {findings}"
    )
    assert any(f.startswith("bracketed:") for f in findings), (
        f"fixture {fixture.name} should trigger the bracketed-form pattern; "
        f"findings: {findings}"
    )
````

- [ ] **Step A.1.3: Run the test — expect partial GREEN, full GREEN, depending on `scripts/*.py` state**

```bash
cd /Users/theo/Projects/engineering-docs-agent && python -m pytest tests/ci/test_docstring_flag_value_lint.py -v
```

Expected:

- `test_no_unwrapped_flag_value_in_docstrings[scaffold_workflow.py]` and all other parametrized cases PASS (post-CCE-80 fix should leave scripts clean)
- `test_fixture_triggers_lint` PASSES (proves the lint detects the regression class)

If `test_no_unwrapped_flag_value_in_docstrings` FAILS on any `scripts/*.py` file, that file has the bug class — surface it; the lint is doing its job.

- [ ] **Step A.1.4: Commit Step A.1's three changes**

```bash
git -C /Users/theo/Projects/engineering-docs-agent add tests/ci/test_docstring_flag_value_lint.py tests/ci/fixtures/regression_docstring.py && \
git -C /Users/theo/Projects/engineering-docs-agent commit -m "test(ci): CCE-87 — docstring --FLAG VALUE lint + regression fixture

Defensive test that fails on the CCE-80 class of bug (mkdocs-autorefs
WARNINGs from bare --FLAG VALUE shapes in scripts/*.py docstrings).
Two patterns detected: bare form ('  --foo BAR') and bracketed form
('[--foo BAR]'). Code regions (triple-backtick fences, inline backticks,
reST Usage:: literal blocks) are stripped before regex application.

Includes a self-check (test_fixture_triggers_lint) that asserts the
synthetic regression fixture trips the lint — protects against the lint
silently stopping work.

Refs CCE-87 / CCE-80 (parent)."
```

### Task A.2 — CCE-85: narrow docs.yml paths trigger

- [ ] **Step A.2.1: Update `.github/workflows/docs.yml` paths**

Anchor on the unique `pull_request:` block. Both `push.paths` and `pull_request.paths` get the two negation patterns; the order matters in GitHub Actions `paths:` matching (positive patterns first, then negations).

Edit `/Users/theo/Projects/engineering-docs-agent/.github/workflows/docs.yml` — replace both `paths:` blocks:

Old (lines 6-12, push.paths):

```yaml
paths:
  - "docs/**"
  - "scripts/verify_diagrams.py"
  - "tests/diagrams/**"
  - "tests/fixtures/diagrams/render/**"
  - "requirements-docs.txt"
  - ".github/workflows/docs.yml"
```

New (push.paths):

```yaml
paths:
  - "docs/**"
  - "!docs/runbooks/**"
  - "!docs/superpowers/**"
  - "scripts/verify_diagrams.py"
  - "tests/diagrams/**"
  - "tests/fixtures/diagrams/render/**"
  - "requirements-docs.txt"
  - ".github/workflows/docs.yml"
```

Same change to the `pull_request.paths` block (lines 15-21).

Use the Edit tool with `replace_all: true` for the unique 6-line YAML block (it appears identically in both push and pull_request, so `replace_all` is correct here).

- [ ] **Step A.2.2: Verify with actionlint**

```bash
cd /Users/theo/Projects/engineering-docs-agent && actionlint .github/workflows/docs.yml 2>&1
```

Expected: empty output (no errors). If actionlint isn't installed, fall back to `python -c "import yaml; yaml.safe_load(open('.github/workflows/docs.yml'))"` and confirm no parse errors.

- [ ] **Step A.2.3: Commit Step A.2's change**

```bash
git -C /Users/theo/Projects/engineering-docs-agent add .github/workflows/docs.yml && \
git -C /Users/theo/Projects/engineering-docs-agent commit -m "ci(docs): CCE-85 — skip diagram-gate on runbooks/superpowers-only PRs

Adds GitHub Actions paths-negation patterns to both push and pull_request
triggers in docs.yml: docs/runbooks/** and docs/superpowers/** changes
no longer fire the gate. These directories carry operator playbooks and
work-tracking artifacts that don't affect the published mkdocs site;
firing diagram-gate on them wastes CI and creates PR-review noise.

Acceptance verified at PR time via the GitHub PR 'files changed'
preview (test plan in PR body).

Refs CCE-85 / CCE-80 (parent)."
```

### Task A.3 — Component A post-implementation 3-agent gate

- [ ] **Step A.3.1: Dispatch three independent agents in parallel against HEAD of the branch (~2 commits since branching).**

**Agent #1 — spec compliance:** verifies CCE-87's lint matches the ticket's regex patterns (`r'^\s+--[a-z][a-z_-]+\s+[A-Z][A-Z_]+'` and `r'\[--[a-z][a-z_-]+\s+[A-Z][A-Z_]+\]'`); verifies CCE-85's docs.yml change uses the exact negation patterns from the ticket; verifies commit messages reference the right tickets and parent.

**Agent #2 — test-fidelity / TDD discipline:** confirms the synthetic regression fixture is actually detected by the lint (run the tests fresh against HEAD); confirms `test_fixture_triggers_lint` exists and passes; confirms no existing CI test was weakened or skipped.

**Agent #3 — diff hygiene / scope:** verifies exactly three files modified across two commits; no rewrites of pre-existing tests; no `# TODO`s, `xfail`s, or `skip`s in the new test file; YAML formatting is consistent with the rest of `docs.yml`.

### Task A.4 — Open the PR

- [ ] **Step A.4.1: Write the PR body to `/tmp/pr-body-eda-cce-77-80-hygiene.md`**

Body content drafted at PR-open time; references CCE-85 + CCE-87 acceptance criteria from their respective tickets and the 3-agent post-impl APPROVED verdicts. **REQUIRED body section: "Ordering note: Component A (this PR) must land before Component B (CCE-84 branch-protection admin call) — once `diagram-gate` becomes a REQUIRED check on `main`, this PR's own diagram-gate run (triggered by the `.github/workflows/docs.yml` change in this PR) would have to pass first. Both pass cleanly, but documenting the load-bearing order so a future orchestrator doesn't apply CCE-84 first and accidentally block this PR."**

- [ ] **Step A.4.2: Push branch and open PR**

```bash
git -C /Users/theo/Projects/engineering-docs-agent push -u origin chore/cce-77-80-hygiene-cce-85-87
cd /Users/theo/Projects/engineering-docs-agent && gh pr create \
  --title "ci: CCE-77/CCE-80 cycle hygiene — narrow docs.yml paths + docstring lint" \
  --body-file /tmp/pr-body-eda-cce-77-80-hygiene.md \
  --base main --head chore/cce-77-80-hygiene-cce-85-87
```

- [ ] **Step A.4.3: Watch CI, merge on green, sync local main**

```bash
gh pr checks <PR#> --watch --repo theoju/engineering-docs-agent && \
gh pr merge <PR#> --squash --delete-branch --repo theoju/engineering-docs-agent && \
git -C /Users/theo/Projects/engineering-docs-agent checkout main && \
git -C /Users/theo/Projects/engineering-docs-agent fetch --prune && \
git -C /Users/theo/Projects/engineering-docs-agent merge --ff-only origin/main
```

---

## Component B — CCE-84 branch protection (admin call)

### Task B.1 — Snapshot + update + verify

- [ ] **Step B.1.1: Snapshot current branch protection**

```bash
gh api repos/theoju/engineering-docs-agent/branches/main/protection > /tmp/eda-branch-protection-snapshot.json
jq -r .required_status_checks.contexts[] /tmp/eda-branch-protection-snapshot.json
```

Expected: prints the current required contexts list (likely includes `pytest 3.11`, `pytest 3.12`, `actionlint`).

Save the snapshot for rollback.

- [ ] **Step B.1.2: Read the full snapshot to understand structure**

```bash
cat /tmp/eda-branch-protection-snapshot.json | jq .
```

Note: GitHub's branch protection API requires re-sending the FULL config on PUT (it doesn't merge). The orchestrator constructs the new payload by reading the snapshot, adding `diagram-gate` to `required_status_checks.contexts`, and re-PUT-ing.

- [ ] **Step B.1.3: Build + apply new protection**

```bash
# Extract existing contexts and add diagram-gate.
jq '.required_status_checks.contexts = (.required_status_checks.contexts + ["diagram-gate"] | unique)' \
  /tmp/eda-branch-protection-snapshot.json > /tmp/eda-branch-protection-new.json

# Reconstruct PUT payload (gh api -X PUT needs specific fields, not the GET shape).
# Use the gh API form that takes individual flags rather than a full JSON body
# to avoid GET/PUT schema mismatch:
NEW_CONTEXTS=$(jq -r '.required_status_checks.contexts | join(",")' /tmp/eda-branch-protection-new.json)

# IMPORTANT: this is the PROPOSED admin call. The orchestrator pauses here
# for explicit user approval before executing.
echo "WOULD RUN: gh api -X PUT repos/theoju/engineering-docs-agent/branches/main/protection \\"
echo "  --input /tmp/eda-branch-protection-put-payload.json"
```

The exact `gh api -X PUT` form depends on the snapshot's full shape; the orchestrator constructs the payload at runtime by reading the snapshot and re-emitting it with `diagram-gate` added to `required_status_checks.contexts`. The orchestrator pauses for explicit user approval before sending the PUT (this is a destructive admin op on protected-branch settings).

- [ ] **Step B.1.4: Verify**

```bash
gh api repos/theoju/engineering-docs-agent/branches/main/protection | jq -r .required_status_checks.contexts[]
```

Expected output includes `diagram-gate` plus the prior contexts.

- [ ] **Step B.1.5: Rollback recipe (DO NOT RUN — kept for emergencies)**

```bash
# If something is wrong with the new protection, restore from snapshot:
# (Same payload-construction approach as Step B.1.3, but using
# /tmp/eda-branch-protection-snapshot.json verbatim.)
```

### Task B.2 — Component B post-implementation gate (1 verification agent — proportional to the work)

- [ ] **Step B.2.1: Dispatch ONE verification agent.**

The Component B work is a single admin call with deterministic verification. A 3-agent gate would be theater; one agent that re-runs the verification and inspects the snapshot suffices.

**Agent — verification:** runs `gh api .../branches/main/protection | jq -r .required_status_checks.contexts[]`, asserts `diagram-gate` is present and the prior contexts are unchanged. Diffs against the snapshot at `/tmp/eda-branch-protection-snapshot.json` and reports any unexpected field drift (e.g., `enforce_admins`, `allow_force_pushes`).

---

## Component C — CCE-88 `/ship -f` regex upgrade (user-home edit)

### Task C.1 — TDD: extend the test harness with new cases (RED first)

- [ ] **Step C.1.1: Snapshot the pre-edit file (two-tier: ephemeral + reboot-durable)**

```bash
# Ephemeral (for in-session diff at Step C.3.1):
cp /Users/theo/.claude/skills/ship/lib/validate-git-cmd.sh /tmp/validate-git-cmd.sh.pre-cce88
cp /Users/theo/.claude/skills/ship/tests/validate-git-cmd.test.sh /tmp/validate-git-cmd.test.sh.pre-cce88

# Reboot-durable (co-located, one-cp rollback if a future session needs it):
cp /Users/theo/.claude/skills/ship/lib/validate-git-cmd.sh /Users/theo/.claude/skills/ship/lib/validate-git-cmd.sh.pre-cce-88-backup
cp /Users/theo/.claude/skills/ship/tests/validate-git-cmd.test.sh /Users/theo/.claude/skills/ship/tests/validate-git-cmd.test.sh.pre-cce-88-backup
```

The `/tmp/` snapshots are for the in-session diff record at Step C.3.1. The `.pre-cce-88-backup` copies in the skill directory survive reboots and are the canonical rollback if a regression surfaces days later (one `cp` away). The `.test.sh.orig` and `.pre-cce-88-backup` files in the tests/ directory are not test files (don't end in `.test.sh`) so the test harness skips them.

- [ ] **Step C.1.2: Append new test cases to `validate-git-cmd.test.sh` (RED phase)**

Append to `/Users/theo/.claude/skills/ship/tests/validate-git-cmd.test.sh`:

```bash

# CCE-88: regex upgrade closes v1 false negatives.
# Cases 20-25: positive — git <subcommand> -f forms that v1 missed.

# Case 20: git checkout -f blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git checkout -f main"}}')
assert_exit "$rc" "2" "git checkout -f blocked (CCE-88)"

# Case 21: git clean -f blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git clean -f"}}')
assert_exit "$rc" "2" "git clean -f blocked (CCE-88)"

# Case 22: git clean -fd blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git clean -fd"}}')
assert_exit "$rc" "2" "git clean -fd blocked (CCE-88)"

# Case 23: git branch -f blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git branch -f release"}}')
assert_exit "$rc" "2" "git branch -f blocked (CCE-88)"

# Case 24: git tag -f blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git tag -f v1.0.0"}}')
assert_exit "$rc" "2" "git tag -f blocked (CCE-88)"

# Case 25: pipeline form — cd repo && git checkout -f main still blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"cd repo && git checkout -f main"}}')
assert_exit "$rc" "2" "pipeline git checkout -f blocked (CCE-88)"

# Cases 26-29: negative regression — non-git -f forms remain unblocked.

# Case 26: rm -f /tmp/* — still not blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"rm -f /tmp/foo"}}')
assert_exit "$rc" "0" "rm -f still not blocked (CCE-88 regression check)"

# Case 27: grep -f patterns.txt — still not blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"grep -f patterns.txt input"}}')
assert_exit "$rc" "0" "grep -f still not blocked (CCE-88 regression check)"

# Case 28: find -f — still not blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"find . -f -name foo"}}')
assert_exit "$rc" "0" "find -f still not blocked (CCE-88 regression check)"

# Case 29: tar -f archive.tar — still not blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"tar -f archive.tar -x"}}')
assert_exit "$rc" "0" "tar -f still not blocked (CCE-88 regression check)"

# Case 30: stderr message for git checkout -f mentions correct subcommand
echo '{"tool_name":"Bash","tool_input":{"command":"git checkout -f main"}}' | bash "$LIB" 2>/tmp/ship-validator-stderr >/dev/null
err=$(cat /tmp/ship-validator-stderr)
if [[ "$err" == *"-f (on git checkout)"* ]]; then
  HARNESS_PASS=$((HARNESS_PASS+1))
else
  echo "FAIL [$HARNESS_NAME]: stderr did not include '-f (on git checkout)' on block: $err"
  HARNESS_FAIL=$((HARNESS_FAIL+1))
fi
rm -f /tmp/ship-validator-stderr

# Cases 31-32: git global options preceding the destructive subcommand still blocked.

# Case 31: git -C <path> checkout -f blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git -C /tmp/repo checkout -f main"}}')
assert_exit "$rc" "2" "git -C <path> checkout -f blocked (CCE-88)"

# Case 32: git -c key=val push -f blocked
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git -c safe.directory=* push -f origin main"}}')
assert_exit "$rc" "2" "git -c key=val push -f blocked (CCE-88)"

# Case 33: regression — git pushd (NOT a real subcommand) must NOT match push prefix
rc=$(run_validator '{"tool_name":"Bash","tool_input":{"command":"git pushd /tmp -f"}}')
assert_exit "$rc" "0" "git pushd -f not blocked (regex anchors on enumerated subcommands, not prefixes)"
```

Note: Case 33 protects against substring/prefix false positives. `pushd` shares the `push` prefix; the regex requires the subcommand to be followed by `[[:space:]]+[^[:space:]]+` or directly by `[[:space:]]-f`, so `pushd ` (whose next char is `d`, not space) cannot satisfy the boundary. Re-tested in Step C.2.2.

Use the Edit tool to append after the existing Case 19 (lines 102–111). The unique anchor is the closing `rm -f /tmp/ship-validator-stderr` after Case 19.

- [ ] **Step C.1.3: Run tests — expect RED on Cases 20-25 and 30 (positive cases unsupported by v1), GREEN on Cases 26-29 (negatives already work)**

```bash
bash /Users/theo/.claude/skills/ship/tests/run.sh
```

Expected: harness reports `Failed: 7` (Cases 20-25 + 30 — all positives that the v1 glob fallback doesn't catch).

If `Failed: 0` already, the v1 fallback is wider than CCE-88's ticket claims — investigate before proceeding (the spec needs revision). If `Failed: > 7`, surface the unexpected failures.

### Task C.2 — Apply the regex upgrade (GREEN phase)

- [ ] **Step C.2.1: Replace lines 39-48 of `validate-git-cmd.sh` with the variable-assigned regex**

Edit `/Users/theo/.claude/skills/ship/lib/validate-git-cmd.sh` — old_string anchored on the unique CCE-77 block:

Old (lines 39-48):

```bash
# Short -f: only block in git push/commit contexts (CCE-77 — was over-matching rm -f, mv -f, find -f, grep -f, tar -f).
# Token boundary: -f preceded by space, followed by space or end of string.
if [[ " $CMD " == *" -f "* ]]; then
  if [[ "$CMD" == *"git push"* ]]; then
    block "-f (on git push)"
  elif [[ "$CMD" == *"git commit"* ]]; then
    block "-f (on git commit)"
  fi
  # Otherwise: -f is a legitimate flag on another command — not blocked.
fi
```

New:

```bash
# Short -f (CCE-77 + CCE-88): only block when -f is a flag on a git destructive subcommand.
# Subcommands covered: push, commit, checkout, clean, branch, tag.
# Anchor on segment boundaries (^|;|&|||(|backtick|whitespace) to defeat substrings like "git pushd".
# Tolerates zero or more git GLOBAL options between `git` and the subcommand
# (e.g., `git -C /path push -f`, `git -c safe.directory=* checkout -f`).
# Variable-assigned regex for bash 3.2.57 compatibility (inline bracket-class regex mis-parses on macOS system bash).
GIT_DESTRUCTIVE_F_RE='(^|[[:space:]]|;|\&|\||\()git[[:space:]]+(-[a-zA-Z][a-zA-Z]*[[:space:]]+[^[:space:]]+[[:space:]]+)*(push|commit|checkout|clean|branch|tag)([[:space:]]+[^|;&()]*)?[[:space:]]-f([[:space:]]|$)'
if [[ "$CMD" =~ $GIT_DESTRUCTIVE_F_RE ]]; then
  subcmd="${BASH_REMATCH[3]:-unknown}"
  block "-f (on git ${subcmd})"
fi
```

Group numbering: group 1 = boundary, group 2 = optional global-option repetition (may be empty), group 3 = subcommand, group 4 = optional middle args. `BASH_REMATCH[3]` is the subcommand name.

- [ ] **Step C.2.2: Run tests — expect ALL GREEN**

```bash
bash /Users/theo/.claude/skills/ship/tests/run.sh
```

Expected: `Failed: 0`, `Passed: ` ≥ 30 (the original 19 + the 11 new).

If any case fails:

- If a positive case (Cases 20-25, 30) fails, the regex doesn't match the form — refine the regex (likely a segment-boundary or whitespace issue), DO NOT weaken the test.
- If a negative case (Cases 26-29) fails, the regex over-matches — tighten the regex, DO NOT weaken the test.
- If an OLD case (Cases 11-15) fails, the regex regressed CCE-77's non-git protection — fix the regex.

- [ ] **Step C.2.3: `bash -n` parse check (bash 3.2.57 compatibility)**

```bash
/bin/bash -n /Users/theo/.claude/skills/ship/lib/validate-git-cmd.sh
echo "parse-check exit: $?"
```

Expected: exit `0`. Uses macOS system `/bin/bash` explicitly (which is 3.2.57), not the homebrew bash 5 that might be first in PATH.

- [ ] **Step C.2.4: `set -u` safety verification**

The existing Case 19 covers this (line 103). It runs as part of Step C.2.2; explicitly re-confirm:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git checkout -f main"}}' | /bin/bash /Users/theo/.claude/skills/ship/lib/validate-git-cmd.sh 2>/tmp/ship-stderr >/dev/null
grep -E "unbound variable|syntax error" /tmp/ship-stderr && echo FAIL || echo PASS
```

Expected: `PASS`.

### Task C.3 — Commit-equivalent record

- [ ] **Step C.3.1: Create the `.changelog/` directory if absent and write the diff**

```bash
mkdir -p /Users/theo/.claude/skills/ship/.changelog
diff -u /tmp/validate-git-cmd.sh.pre-cce88 /Users/theo/.claude/skills/ship/lib/validate-git-cmd.sh > /Users/theo/.claude/skills/ship/.changelog/2026-06-04-cce-88.diff
diff -u /tmp/validate-git-cmd.test.sh.pre-cce88 /Users/theo/.claude/skills/ship/tests/validate-git-cmd.test.sh >> /Users/theo/.claude/skills/ship/.changelog/2026-06-04-cce-88.diff
wc -l /Users/theo/.claude/skills/ship/.changelog/2026-06-04-cce-88.diff
```

Expected: ~30-40 lines of unified diff covering both files.

### Task C.4 — Component C post-implementation 3-agent gate

- [ ] **Step C.4.1: Dispatch three independent agents in parallel.**

**Agent #1 — spec compliance:** verifies the new regex uses variable-assigned form (not inline), enumerates exactly the 6 subcommands from CCE-88 (`push, commit, checkout, clean, branch, tag`), preserves the `-f (on git <subcommand>)` stderr format, and that bash 3.2.57 parse-check passes.

**Agent #2 — test coverage:** runs `bash /Users/theo/.claude/skills/ship/tests/run.sh` independently, confirms all 30+ test cases pass, confirms the 6 positive CCE-88 cases (Cases 20-25) and 4 negative-regression cases (26-29) AND the stderr-format Case 30 all PASS, AND that the CCE-77 cases 11-17 still PASS.

**Agent #3 — safety / set -u / parse:** runs `/bin/bash -n` parse-check explicitly under macOS system bash, runs the set -u case independently, and verifies the diff snapshot at `~/.claude/skills/ship/.changelog/2026-06-04-cce-88.diff` exists, is non-empty, and contains both the lib and tests edits.

---

## Component D — Jira close-out (4 transitions, per-action auth)

After Components A, B, C all complete, transition each ticket to Done with a close-out comment. Each `transitionJiraIssue` and `addCommentToJiraIssue` call needs explicit per-action user authorization (per CLAUDE.md hard rule).

- [ ] **Step D.1: CCE-85 → Done.** Comment: PR-EDA URL + merge commit SHA + the 4 AC checkmarks. Pause for user go on `transitionJiraIssue`.
- [ ] **Step D.2: CCE-87 → Done.** Comment: same PR URL + test pass count + `test_fixture_triggers_lint` confirmation. Pause for user go.
- [ ] **Step D.3: CCE-84 → Done.** Comment: snapshot path + `gh api ... | jq` verification output. Pause for user go.
- [ ] **Step D.4: CCE-88 → Done.** Comment: pre/post test counts (19 → 30+), `~/.claude/skills/ship/.changelog/2026-06-04-cce-88.diff` path. Pause for user go.

---

## Self-Review

**Spec coverage:**

- Spec §Goals (1) "Land CCE-85+87 as single PR" → Tasks A.1, A.2, A.4
- Spec §Goals (2) "Apply CCE-84 admin call" → Task B.1
- Spec §Goals (3) "Apply CCE-88 regex" → Tasks C.1, C.2, C.3
- Spec §Goals (4) "Close all 4 Jira" → Component D
- Spec §Acceptance criteria 1–5 → all covered with verification commands in their respective tasks

**Type consistency:** branch name (`chore/cce-77-80-hygiene-cce-85-87`) consistent across plan; file paths absolute throughout; commit message format consistent; the regex variable name `GIT_DESTRUCTIVE_F_RE` is unique and consistent.

**Placeholder scan:** PR# in Step A.4.3 is a runtime substitution (PR doesn't exist yet at plan time). The exact `gh api -X PUT` payload in Step B.1.3 is constructed at runtime from the snapshot (this is correct — GitHub's PUT requires the FULL config and we don't want to hardcode it). The PR body in Step A.4.1 is constructed at PR-open time after post-impl gate verdicts are in (so the body can reference them).

No gaps.

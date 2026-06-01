# CCE-75 polish follow-up — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task (inline execution chosen — surface is too small to justify `subagent-driven-development` overhead). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the 3 non-blocking polish items the CCE-75 validator panel surfaced, with scope refined by empirical verification: docstring + symlink-assumption comment + two anti-regression tests (one for intended behavior, one for correct-pathspec-behavior).

**Architecture:** Surgical edits to `scripts/orchestrator_runner.py::_stage_docs_run_changes` (docstring + inline comment only — no code change) plus two new tests in `tests/orchestrator/test_gitlink_exclusion.py`. Single function, zero structural change.

**Tech Stack:** Python 3.11/3.12, pytest, git (CLI), subprocess.

---

## Context

After CCE-75 (PR #97, commit `4cc258a`) shipped, three independent validators flagged 3 non-blocking polish items:

- **Item A** — docstring should note that mid-run modifications to tracked content under `.docs-agent-plugin/` are dropped from the docs commit. (Intended behavior; the existing docstring covers HEAD-content preservation but not the modify-during-run case.)
- **Item B** — original validator concern: bare pathspec `git diff -- .docs-agent-plugin` could over-select a sibling like `.docs-agent-plugin-notes.md`. **Empirically refuted** — git pathspec requires exact match OR prefix-followed-by-slash, not arbitrary prefix-match. Reverified in `/tmp/tmp.EN1oJ8ns06/`: bare pathspec returns only `.docs-agent-plugin/inner.txt`, leaves the sibling staged. **Item B becomes an anti-regression test instead of a code change** — locks in correct behavior so a future contributor doesn't "fix" something that isn't broken.
- **Item C** — inline comment noting the helper assumes `.docs-agent-plugin` is a real directory (per actions/checkout), not a symlink. Pure advisory, no behavior change.

## File map

- **Modify:** `scripts/orchestrator_runner.py` — function `_stage_docs_run_changes` (lines 1742–1810). Docstring add (~3 lines) + inline comment (~2 lines). No subprocess argv change.
- **Modify:** `tests/orchestrator/test_gitlink_exclusion.py` — add 2 tests at end of file. Reuse existing `_init_git_repo` and `_create_nested_plugin_checkout` helpers.

## Validator strategy

Light tier per the agreed small→medium→large scaling: single self-review of the plan + a 3-validator panel for confirmation per user request. Inline execution after panel converges, then `/ship`.

---

## Task 1: Pin "mid-run mods dropped" behavior (Item A test)

**Files:**

- Test: `tests/orchestrator/test_gitlink_exclusion.py` (append new test at end)

- [ ] **Step 1: Write the failing/passing test**

Append to `tests/orchestrator/test_gitlink_exclusion.py`:

```python
def test_stage_docs_run_changes_drops_midrun_modifications_to_tracked_plugin_content(
    tmp_path: Path,
) -> None:
    """CCE-75 polish: mid-run modifications to tracked content under
    `.docs-agent-plugin/` are intentionally dropped from the docs commit.

    The helper's `restore --staged` step is gated only on whether ANY
    `.docs-agent-plugin/*` entry made it into the index. When a host has
    pre-tracked content there AND it's been modified during the run
    (orchestrator bug, careless subagent write, whatever), the
    modification gets staged by `git add -A .` and then reverted out by
    the restore step. The net effect: the modification is silently not
    committed. This is intended behavior — docs runs should never mutate
    the plugin tree on the runner.
    """
    _init_git_repo(tmp_path)
    plugin = tmp_path / ".docs-agent-plugin"
    plugin.mkdir()
    (plugin / "tracked.txt").write_text("baseline content\n")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", ".docs-agent-plugin"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "pre-tracked plugin content"],
        check=True,
    )

    (plugin / "tracked.txt").write_text("MUTATED MID-RUN\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text("# authored page\n")

    rc, stderr = orun._stage_docs_run_changes(tmp_path)
    assert rc == 0, f"staging failed: rc={rc}, stderr={stderr!r}"

    staged_diff = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--", ".docs-agent-plugin"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "MUTATED MID-RUN" not in staged_diff, (
        f"mid-run modification to tracked plugin content must NOT be staged; "
        f"got staged diff: {staged_diff!r}"
    )

    staged_files = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "docs/page.md" in staged_files, (
        f"authored docs page must be staged; got {staged_files}"
    )
```

- [ ] **Step 2: Run the test to confirm behavior**

Run:

```bash
python3 -m pytest tests/orchestrator/test_gitlink_exclusion.py::test_stage_docs_run_changes_drops_midrun_modifications_to_tracked_plugin_content -v
```

Expected: **PASS** on the current code (the behavior is already implemented by `restore --staged --` reverting the index entry). If it FAILS, the test caught a discrepancy between docstring claim and actual behavior — STOP and investigate before proceeding.

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/test_gitlink_exclusion.py
git commit -m "$(cat <<'EOF'
test(CCE-75): pin mid-run-mods-dropped behavior

Adds anti-regression test for the validator-flagged "mid-run
modifications to tracked plugin content are dropped" behavior of
_stage_docs_run_changes. The behavior is already correct on main
(git restore --staged reverts the index entry); this test prevents
future refactors from silently regressing it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Pin "bare pathspec doesn't over-select siblings" (Item B → anti-regression test)

**Files:**

- Test: `tests/orchestrator/test_gitlink_exclusion.py` (append second test)

- [ ] **Step 1: Write the passing test**

Append to `tests/orchestrator/test_gitlink_exclusion.py`:

```python
def test_stage_docs_run_changes_bare_pathspec_does_not_overselect_siblings(
    tmp_path: Path,
) -> None:
    """CCE-75 polish: bare pathspec `-- .docs-agent-plugin` matches only
    the exact path or `path/*` — NOT arbitrary prefixes.

    Git pathspec matching rule: a literal pathspec matches if and only
    if the path equals the spec OR begins with `<spec>/`. So `.docs-agent-plugin`
    matches `.docs-agent-plugin` itself and `.docs-agent-plugin/anything`,
    but NOT `.docs-agent-plugin-notes.md` (no trailing slash).

    A validator panel suggested tightening the pathspec to
    `:(glob).docs-agent-plugin/**` to "prevent prefix over-select."
    Empirical verification proved bare pathspec is already correct;
    this test locks in that behavior so a future contributor does not
    introduce a `:(glob)` "tightening" that would itself narrow scope
    incorrectly (e.g., dropping the gitlink entry which sits at
    `.docs-agent-plugin` without a trailing slash).
    """
    _init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".docs-agent-plugin/\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "host gitignore"],
        check=True,
    )

    (tmp_path / ".docs-agent-plugin-notes.md").write_text(
        "# notes about the docs-agent plugin\n"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text("# authored page\n")

    rc, stderr = orun._stage_docs_run_changes(tmp_path)
    assert rc == 0, f"staging failed: rc={rc}, stderr={stderr!r}"

    staged_files = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert ".docs-agent-plugin-notes.md" in staged_files, (
        f"sibling file at repo root must stay staged; bare-pathname pathspec "
        f"should match only `.docs-agent-plugin` or `.docs-agent-plugin/*`. "
        f"got staged: {staged_files}"
    )
    assert "docs/page.md" in staged_files
```

- [ ] **Step 2: Run the test to confirm it passes**

Run:

```bash
python3 -m pytest tests/orchestrator/test_gitlink_exclusion.py::test_stage_docs_run_changes_bare_pathspec_does_not_overselect_siblings -v
```

Expected: **PASS** (bare pathspec is empirically correct, verified in `/tmp/tmp.EN1oJ8ns06/`).

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/test_gitlink_exclusion.py
git commit -m "$(cat <<'EOF'
test(CCE-75): lock in bare-pathspec correctness anti-regression

Validator panel originally suggested tightening
`git diff -- .docs-agent-plugin` to `:(glob).docs-agent-plugin/**`
to prevent prefix over-select against siblings like
`.docs-agent-plugin-notes.md`. Empirical verification proved
bare pathspec is already correct — git pathspec requires exact
match OR prefix-followed-by-slash. This test pins that behavior
so future refactors do not introduce a misguided `:(glob)`
tightening (which would itself fail to match the gitlink entry
at `.docs-agent-plugin` without trailing slash).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Docstring (Item A) + symlink comment (Item C)

**Files:**

- Modify: `scripts/orchestrator_runner.py:1742-1768` (`_stage_docs_run_changes` docstring) + add inline comment above the `add` subprocess call (~line 1769–1772)

- [ ] **Step 1: Locate the docstring end (line ~1768) and the add-subprocess start (line ~1769)**

Run:

```bash
grep -n "def _stage_docs_run_changes\|subprocess.run" scripts/orchestrator_runner.py | head -6
```

Confirm the function spans the expected range.

- [ ] **Step 2: Add Item A paragraph to docstring**

Use the `Edit` tool to insert the new paragraph at the end of the docstring (before the closing `"""`), after the existing paragraph that starts "The prior implementation used a negative pathspec":

Find this existing text (matches an entire paragraph at the end of the docstring):

```python
    The prior implementation used a negative pathspec
    (`:!.docs-agent-plugin`), which collided with host `.gitignore`
    entries: naming a path in a pathspec promotes it to "explicitly
    mentioned", which triggers git's gitignore-aware safety check —
    failing with `paths are ignored by one of your .gitignore files`.
    """
```

Replace with:

```python
    The prior implementation used a negative pathspec
    (`:!.docs-agent-plugin`), which collided with host `.gitignore`
    entries: naming a path in a pathspec promotes it to "explicitly
    mentioned", which triggers git's gitignore-aware safety check —
    failing with `paths are ignored by one of your .gitignore files`.

    Mid-run modifications to tracked content under `.docs-agent-plugin/`
    are intentionally dropped from the docs commit: `git add -A .` stages
    them, then `git restore --staged --` reverts the index back to HEAD.
    Docs runs should never mutate the plugin tree on the runner, so this
    is correct — but it does mean an orchestrator bug that touched plugin
    files would fail silently in the docs PR. (Pinned by
    `test_stage_docs_run_changes_drops_midrun_modifications_to_tracked_plugin_content`.)
    """
```

- [ ] **Step 3: Add Item C symlink-assumption inline comment**

Find this text:

```python
    add = subprocess.run(
        ["git", "-C", str(repo_root), "add", "-A", "."],
        capture_output=True,
        text=True,
    )
```

Replace with (adds 2-line comment above the call):

```python
    # Assumes `.docs-agent-plugin/` is a real directory (per
    # actions/checkout@v5), not a symlink. A symlink at that path
    # would let `add -A .` recurse into its target and over-stage.
    add = subprocess.run(
        ["git", "-C", str(repo_root), "add", "-A", "."],
        capture_output=True,
        text=True,
    )
```

- [ ] **Step 4: Run the full test suite to confirm no regressions**

Run:

```bash
python3 -m pytest -q
```

Expected: **686 passed, 3 skipped** in ~45s. (684 prior + 2 new from Tasks 1 and 2.)

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
docs(CCE-75): _stage_docs_run_changes — note mid-run-mods + symlink

Adds docstring paragraph documenting that mid-run modifications to
tracked content under `.docs-agent-plugin/` are intentionally dropped
from the docs commit (behavior pinned by the test added in the prior
commit).

Adds inline comment noting the helper assumes `.docs-agent-plugin/`
is a real directory (per actions/checkout@v5), not a symlink.

Both items surfaced by the CCE-75 ship-time validator panel.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Ship

- [ ] **Step 1: Verify integrated suite once more**

```bash
git fetch origin main
git merge --no-ff --no-commit origin/main
git status --short
```

Expected: `Already up to date.` or a fast-forward summary. If conflicts, STOP and resolve.

If a merge actually happened, run:

```bash
python3 -m pytest -q
```

Expected: 686 passed, 3 skipped.

- [ ] **Step 2: /ship via the user-level skill**

Run the `/ship` skill with the polish branch's context. Standard 7-stage pipeline; pre-flight, test (already green), verify-agent, simplify (likely no-op), code-review, commit (no-op — already committed across Tasks 1/2/3), push + PR, Jira (no-op — CCE-75 already Done; ship's extract-jira-key will pull `CCE-75` from branch name but post a comment without status transition).

- [ ] **Step 3: After PR opens, verify all status checks green**

```bash
gh pr view <PR#> -R theoju/engineering-docs-agent --json statusCheckRollup
```

Expected: actionlint ✓, pytest (3.11) ✓, pytest (3.12) ✓.

- [ ] **Step 4: Squash-merge and clean up**

```bash
gh pr merge <PR#> -R theoju/engineering-docs-agent --squash --delete-branch
git checkout main && git pull --ff-only origin main
git branch -d chore/CCE-75-polish
```

- [ ] **Step 5: Post a closeout comment on CCE-75 (no transition — already Done)**

Use `mcp__plugin_atlassian_atlassian__addCommentToJiraIssue` with body summarizing: polish PR URL, 2 new anti-regression tests, doc/comment additions, empirical finding on bare pathspec correctness.

---

## Acceptance criteria

- 686 tests pass (684 + 2 new), 3 skipped — full suite, no regressions
- Item A test PASSES on both pre-patch and post-patch code (it's an anti-regression test, behavior already correct)
- Item B test PASSES on bare pathspec (empirically verified before plan was written)
- Item C comment + Item A docstring paragraph are factually accurate
- PR squash-merged, branch deleted, main fast-forwarded
- CCE-75 Jira receives a brief closeout comment with PR URL (no status transition; CCE-75 stays Done)

## Risks

- **Risk:** Item A test fails on current code (would indicate a hidden bug between docstring claim and actual behavior). **Mitigation:** Step 1.2 explicitly looks for FAIL and STOPS if found — don't paper over.
- **Risk:** Item C comment becomes wrong if actions/checkout@v5 ever switches to a symlink representation. **Mitigation:** none — it's an advisory comment; if the assumption breaks we'd see a test failure elsewhere and revisit.
- **Risk:** The branch is 3 commits not 1. **Mitigation:** acceptable — squash-merge consolidates them at PR merge; the commit-per-task structure aids review.

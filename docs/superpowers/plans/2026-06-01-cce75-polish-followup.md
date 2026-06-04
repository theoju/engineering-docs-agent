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

Expected: **PASS** on the current code. Mechanism: `git add -A .` (line ~1769) stages the modified `tracked.txt`, the diff probe (line ~1779-1792) finds `.docs-agent-plugin/tracked.txt` in the index, and `git restore --staged -- .docs-agent-plugin` (line ~1798-1811) reverts the index entry to HEAD. If this test FAILS, exactly one of the three steps has drifted — `git log -p scripts/orchestrator_runner.py` and check what changed before touching the test.

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/test_gitlink_exclusion.py
git commit -m "$(cat <<'EOF'
test(CCE-75): assert mid-run plugin mods are dropped from docs commit

Adds anti-regression test for the validator-flagged behavior:
mid-run modifications to tracked content under .docs-agent-plugin/
are reverted from the index by the probe-then-restore pattern in
_stage_docs_run_changes. The behavior is already correct on main;
this test prevents future refactors from silently regressing it.

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
    """CCE-75 polish: bare pathspec `-- .docs-agent-plugin` matches the
    gitlink entry itself AND `<spec>/<anything>` — but NOT siblings like
    `.docs-agent-plugin-notes.md` that share a common string prefix.

    Git pathspec rule: a literal pathspec matches if the path equals the
    spec OR begins with `<spec>/`. A trailing slash is required for
    prefix matching, so `.docs-agent-plugin` does NOT prefix-match
    `.docs-agent-plugin-notes.md`.

    Why this test exists: a validator panel suggested "tightening" the
    pathspec to `:(glob).docs-agent-plugin/**` on the assumption that
    the bare form over-selects. Empirical verification proved otherwise.
    A `:(glob)` rewrite would actively REGRESS the helper, because the
    gitlink entry sits at `.docs-agent-plugin` with no trailing slash
    and would not match `.../**`. This test locks in both halves of the
    correct behavior so a future "tightening" attempt is caught:

    (1) Direct pathspec assertion — the bare-form `git diff --cached --
        .docs-agent-plugin` MUST include the gitlink (a `:(glob)/**`
        rewrite breaks this) AND MUST NOT include the sibling.
    (2) End-to-end via helper — sibling stays staged, plugin tree gets
        unstaged.
    """
    _init_git_repo(tmp_path)

    # Sibling at repo root that shares a string prefix with the plugin path
    (tmp_path / ".docs-agent-plugin-notes.md").write_text(
        "# notes about the docs-agent plugin\n"
    )
    # Legitimate docs output the helper should stage
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text("# authored page\n")
    # Real plugin checkout so the diff probe has a gitlink entry to find
    # (and the restore step actually fires inside the helper)
    _create_nested_plugin_checkout(tmp_path)

    # === Direct pathspec assertion (the property a :(glob) rewrite breaks) ===
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "-A", "."],
        capture_output=True,
        text=True,
        check=True,
    )
    bare_match = subprocess.run(
        [
            "git", "-C", str(tmp_path),
            "diff", "--cached", "--name-only",
            "--", ".docs-agent-plugin",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert ".docs-agent-plugin" in bare_match, (
        f"bare pathspec MUST match the gitlink entry `.docs-agent-plugin`; "
        f"got: {bare_match}. A `:(glob).docs-agent-plugin/**` rewrite would "
        f"fail this check — the gitlink has no trailing slash."
    )
    assert ".docs-agent-plugin-notes.md" not in bare_match, (
        f"bare pathspec MUST NOT prefix-match `.docs-agent-plugin-notes.md`; "
        f"git pathspec requires exact-match or prefix-followed-by-slash. "
        f"got: {bare_match}"
    )

    # === End-to-end via the helper (sibling survives, plugin tree unstaged) ===
    subprocess.run(["git", "-C", str(tmp_path), "reset", "-q"], check=True)
    rc, stderr = orun._stage_docs_run_changes(tmp_path)
    assert rc == 0, f"staging failed: rc={rc}, stderr={stderr!r}"

    staged_files = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert ".docs-agent-plugin-notes.md" in staged_files, (
        f"sibling at repo root must stay staged after helper run; got: {staged_files}"
    )
    assert "docs/page.md" in staged_files, (
        f"authored docs page must be staged; got: {staged_files}"
    )
    plugin_entries = [
        p for p in staged_files
        if p == ".docs-agent-plugin" or p.startswith(".docs-agent-plugin/")
    ]
    assert not plugin_entries, (
        f"plugin tree must NOT be staged after helper run; got: {plugin_entries}"
    )
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

- Modify: `scripts/orchestrator_runner.py:1742-1813` (`_stage_docs_run_changes` — docstring + add inline comment at the top of the function body, before the first subprocess call)

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
    are dropped from the docs commit: `git add -A .` stages them, the
    diff probe then sees the staged change under `.docs-agent-plugin/`
    and TRIGGERS the `git restore --staged --` step (which is gated on
    the probe finding anything — not unconditional), and the restore
    reverts the index entry back to HEAD. Docs runs should never mutate
    the plugin tree on the runner, so this is correct — but it does mean
    an orchestrator bug that touched plugin files would fail silently in
    the docs PR. (Pinned by tests in
    `tests/orchestrator/test_gitlink_exclusion.py`.)
    """
```

- [ ] **Step 3: Add Item C symlink-assumption inline comment (top of function body, scoped to all three git ops)**

The symlink assumption applies to ALL three git operations in this function (add, diff probe, restore), not just `add` — pathspec resolution against a symlink would shift semantics for each. Place the comment at the top of the function body so the scope is unambiguous.

Find this text (the first subprocess call in the function, immediately after the closing `"""` of the docstring):

```python
    add = subprocess.run(
        ["git", "-C", str(repo_root), "add", "-A", "."],
        capture_output=True,
        text=True,
    )
```

Replace with:

```python
    # The three git operations below all assume `.docs-agent-plugin/`
    # is a real directory (per actions/checkout@v5), not a symlink.
    # A symlink would change pathspec semantics for add/diff/restore
    # alike: `add -A .` would recurse into the target, and the diff
    # probe + restore would match the link rather than its contents.
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

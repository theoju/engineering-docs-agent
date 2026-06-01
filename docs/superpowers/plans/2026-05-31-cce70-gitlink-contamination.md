# CCE-70 — Prevent gitlink contamination of host repos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the orchestrator from staging the host workflow's `.docs-agent-plugin/` checkout as a submodule gitlink. Two-layer fix: (1) extract a `_stage_docs_run_changes(repo_root)` helper that uses git's exclude pathspec; (2) update the setup skill to write `.docs-agent-plugin/` into new hosts' `.gitignore`.

**Architecture:** The orchestrator's `open_or_append_pr` at `scripts/orchestrator_runner.py:1767` currently runs `git -C repo_root add .` after the pipeline writes authored files. This sweeps any nested checkout at `.docs-agent-plugin/` as a gitlink. Replace with a private helper that uses `git add . -- ':!.docs-agent-plugin' ':!.docs-agent-plugin/**'` — git's exclude pathspec magic drops the path from the staged set. The setup skill prompt gains a corresponding instruction so new host onboardings carry the `.gitignore` entry as belt-and-suspenders.

**Tech Stack:** Python stdlib (`subprocess`, `pathlib`), pytest with real git invocations, Markdown skill prompts. No new runtime deps.

**Test runner:** `python3 -m pytest`

**Commit trailer (required on every commit):** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

**Branch:** `fix/CCE-70-gitignore-plugin-checkout` (already checked out off main `6e812a5`).

**Never use:** `-f`, `--force`, `--no-verify`, `--amend`.

**Spec:** `docs/superpowers/specs/2026-05-31-cce70-gitlink-contamination.md`

---

### Task 1: Failing regression tests — staging helper excludes plugin checkout

**Files:**

- Create: `tests/orchestrator/test_gitlink_exclusion.py`

**Rationale:** Lock in the desired staging behavior before writing the helper. Two tests: one asserts the plugin path is NOT staged (the bug); one asserts legitimate files (state.json, whats-new, docs) ARE staged (guards against over-eager exclusion).

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestrator/test_gitlink_exclusion.py` with the exact content:

```python
"""CCE-70: orchestrator must not stage .docs-agent-plugin as a gitlink.

The host's docs-agent-nightly workflow checks out the plugin into
.docs-agent-plugin/. Without an explicit exclude pathspec, `git add .`
would register that nested checkout as a submodule entry (mode 160000)
in the host's docs-agent PR.
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def _init_git_repo(path: Path) -> None:
    """Initialize a real git repo at `path` with author config."""
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.local"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "test"],
        check=True,
    )


def _create_nested_plugin_checkout(host_root: Path) -> None:
    """Create a fake `.docs-agent-plugin/` that looks like a submodule to
    git (a `.git` gitdir reference inside). Mirrors how actions/checkout@v5
    leaves the path in CI runs."""
    plugin = host_root / ".docs-agent-plugin"
    plugin.mkdir()
    (plugin / ".git").write_text("gitdir: /tmp/fake-plugin-git\n")
    (plugin / "README.md").write_text("# plugin sentinel\n")


def test_stage_docs_run_changes_excludes_plugin_checkout(tmp_path: Path) -> None:
    """The staging helper must NOT register .docs-agent-plugin as a gitlink."""
    _init_git_repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "new-page.md").write_text("# new docs page\n")
    _create_nested_plugin_checkout(tmp_path)

    rc, stderr = orun._stage_docs_run_changes(tmp_path)
    assert rc == 0, f"staging failed: rc={rc}, stderr={stderr!r}"

    staged = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip().splitlines()

    assert "docs/new-page.md" in staged, (
        f"authored docs page must be staged; got {staged}"
    )
    assert ".docs-agent-plugin" not in staged, (
        f".docs-agent-plugin must NOT be staged as a gitlink; got {staged}"
    )
    plugin_entries = [p for p in staged if p.startswith(".docs-agent-plugin")]
    assert not plugin_entries, (
        f"no .docs-agent-plugin/* entries should be staged; got {plugin_entries}"
    )


def test_stage_docs_run_changes_stages_state_and_whats_new(tmp_path: Path) -> None:
    """The staging helper must still stage all the run's intended outputs:
    state.json bump, whats-new entry, and the docs pages."""
    _init_git_repo(tmp_path)
    (tmp_path / ".engineering-docs-agent").mkdir()
    (tmp_path / ".engineering-docs-agent" / "state.json").write_text("{}\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "whats-new.md").write_text("# What's new\n")
    (tmp_path / "docs" / "page.md").write_text("# new page\n")

    rc, _ = orun._stage_docs_run_changes(tmp_path)
    assert rc == 0

    staged = set(subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip().splitlines())

    assert ".engineering-docs-agent/state.json" in staged
    assert "docs/whats-new.md" in staged
    assert "docs/page.md" in staged
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_gitlink_exclusion.py -v`

Expected: BOTH FAIL with `AttributeError: module 'orchestrator_runner' has no attribute '_stage_docs_run_changes'`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/orchestrator/test_gitlink_exclusion.py
git commit -m "$(cat <<'EOF'
test(CCE-70): failing regression for gitlink-exclusion staging helper

Two tests in a new file: (1) staging must exclude .docs-agent-plugin (the
nested checkout actions/checkout@v5 creates in CI); (2) staging must still
register state.json, whats-new.md, and authored docs pages — guards against
an over-eager exclude pathspec. Both fail because the _stage_docs_run_changes
helper does not exist yet; Task 2 introduces it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Orchestrator — extract `_stage_docs_run_changes` helper with exclude pathspec

**Files:**

- Modify: `scripts/orchestrator_runner.py` — add helper near other private helpers; update `open_or_append_pr` to call it (around line 1767).

- [ ] **Step 1: Add the helper**

Add a module-level helper. Place it before `open_or_append_pr` (which starts at line 1727), near the other private orchestrator helpers like `_format_partial_digest`. Use this exact body:

```python
def _stage_docs_run_changes(repo_root: Path) -> tuple[int, str]:
    """Stage all run-emitted changes in `repo_root`, excluding the vendored
    plugin checkout at `.docs-agent-plugin/`.

    The host's workflow checks out the plugin into `.docs-agent-plugin/`
    via actions/checkout (see templates/workflow-run.yml). Without an
    explicit exclusion, `git add .` would register the nested checkout as
    a submodule gitlink (mode 160000) in the host's docs-agent PR — CCE-70.
    """
    result = subprocess.run(
        [
            "git", "-C", str(repo_root), "add", ".", "--",
            ":!.docs-agent-plugin",
            ":!.docs-agent-plugin/**",
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stderr.strip()
```

- [ ] **Step 2: Update `open_or_append_pr` to use the helper**

In `scripts/orchestrator_runner.py:1767-1773`, replace:

```python
    add = subprocess.run(
        ["git", "-C", str(repo_root), "add", "."], capture_output=True, text=True
    )
    if add.returncode != 0:
        reasons.append(
            (f"git_add_failed: {add.stderr.strip()[:_STDERR_TRUNCATE]}", False)
        )
        return None, reasons
```

with:

```python
    add_rc, add_stderr = _stage_docs_run_changes(repo_root)
    if add_rc != 0:
        reasons.append(
            (f"git_add_failed: {add_stderr[:_STDERR_TRUNCATE]}", False)
        )
        return None, reasons
```

- [ ] **Step 3: Run Task 1's tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_gitlink_exclusion.py -v`

Expected: BOTH PASS.

- [ ] **Step 4: Run the full test suite**

Run: `python3 -m pytest`

Expected: all tests pass (the existing `test_open_or_append_pr.py` tests stub subprocess so the helper extraction is invisible to them).

- [ ] **Step 5: Commit the orchestrator change**

```bash
git add scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
fix(CCE-70): exclude .docs-agent-plugin from `git add` during docs-agent PR

Extract _stage_docs_run_changes(repo_root) helper. Replaces the bare
`git add .` at the open_or_append_pr staging step with an explicit
exclude pathspec for the vendored plugin checkout that actions/checkout
creates at .docs-agent-plugin/ in host CI runs.

Without this fix, every nightly run on a CCE-57/58-onboarded host stages
the nested checkout as a submodule gitlink (mode 160000) and ships it
in the host's docs-agent PR with a drifting SHA. Caught when ADIS#394
landed a gitlink pointing at the plugin's HEAD at that run.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Setup skill — instruct `.docs-agent-plugin/` `.gitignore` write

**Files:**

- Modify: `skills/engineering-docs-agent-setup/SKILL.md` — extend step 6 (line 33).

- [ ] **Step 1: Locate the step 6 block**

Open `skills/engineering-docs-agent-setup/SKILL.md`. Find the line beginning `6. Write \`.engineering-docs-agent/config.yml\``.

- [ ] **Step 2: Append the `.gitignore` instruction**

Add a new sentence at the end of step 6, after the existing "do not delete the checkout step" sentence:

```markdown
After writing the workflow files, ensure `.docs-agent-plugin/` is in the host repo's `.gitignore`. If `.gitignore` exists, append the line if absent. If `.gitignore` does not exist, create it with that single line. This prevents `git add .` (run by you or by automation outside this orchestrator) from registering the workflow's vendored plugin checkout as a submodule gitlink in host commits — CCE-70.
```

- [ ] **Step 3: Run the full test suite**

Run: `python3 -m pytest`

Expected: all tests pass. SKILL.md changes don't affect Python tests, but verify nothing parses the file in tests.

- [ ] **Step 4: Commit the skill update**

```bash
git add skills/engineering-docs-agent-setup/SKILL.md
git commit -m "$(cat <<'EOF'
fix(CCE-70): setup skill writes .docs-agent-plugin/ to host .gitignore

Adds an explicit instruction to step 6 of the setup skill: after writing
the workflow files, ensure `.docs-agent-plugin/` is in the host's
.gitignore. Belt-and-suspenders companion to the orchestrator's exclude
pathspec — protects against any future `git add .` invocation outside
the orchestrator's staging helper.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Full pytest verification + branch state check

**Files:** (no edits — verification only)

- [ ] **Step 1: Run full pytest suite**

Run: `python3 -m pytest -v 2>&1 | tail -25`

Expected: all tests pass. Pay attention to:

- `tests/orchestrator/test_gitlink_exclusion.py` — both new tests pass
- `tests/orchestrator/test_open_or_append_pr.py` — existing tests still pass

- [ ] **Step 2: Verify branch state**

```bash
git log --oneline main..HEAD
git status --short
```

Expected: 5 commits ahead of main (spec, plan, failing tests, orchestrator fix, skill update). Clean working tree.

- [ ] **Step 3: No commit (verification only)**

If green, hand off to /ship. If anything fails, return to the failing task.

---

## Out of scope

- Refactoring `open_or_append_pr` signature to take an explicit staging list.
- Migrating already-onboarded hosts' `.gitignore` retroactively (the orchestrator-side exclusion protects them automatically).
- ADIS host cleanup PR (`git rm --cached .docs-agent-plugin`) — separate work item after this lands.
- Auditing the codebase for any OTHER bare `git add .` calls — own ticket if any are found.

## After Task 4 — handoff

Surface ship-readiness. Controller invokes `/ship` separately. After merge, the ADIS host-cleanup PR follows.

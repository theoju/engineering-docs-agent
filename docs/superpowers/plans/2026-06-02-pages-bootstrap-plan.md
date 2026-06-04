# Pages bootstrap fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the misleading `actions/configure-pages@v6 enablement: true` with a real `gh api` Pages bootstrap call from the setup skill, across the plugin (template + dogfood workflow + new helper script + skill text + tests + CLAUDE.md + CHANGELOG) and the originating consumer host (workflow + test flip + spec annotation + CLAUDE.md pointer).

**Architecture:** Two PRs spanning two repos, fixing one conceptual bug across four surfaces. Plugin PR (deliverables B0-B7) lands the durable fix: new `scripts/enable_pages.py` wrapping `gh api` with 4 failure modes (201 happy / 409 idempotent / gh-missing / all-other-graceful), 9 pytest cases including substring-false-positive regression guard and argv-contract assertion, flipped+hardened existing template test, SKILL.md step 6c, CLAUDE.md convention bullet, dogfood workflow cleanup, CHANGELOG entry. Consumer PR (deliverables A1-A4) is a small drive-by mirroring the workflow cleanup, test flip, spec annotation, and CLAUDE.md pointer update.

**Tech Stack:** Python 3.9+ (stdlib only — `argparse`, `re`, `shutil`, `subprocess`), pytest, `pyyaml` (already a plugin dep), `gh` CLI (admin scope, operator-side), GitHub Actions workflow YAML, vitest + Node for consumer-side test, markdown for skill/CLAUDE.md/CHANGELOG.

**Spec:** `/Users/theo/Projects/engineering-docs-agent/docs/superpowers/specs/2026-06-02-pages-bootstrap-design.md`

---

## Executor logistics (read before starting)

- **Plugin work** happens in `/Users/theo/Projects/engineering-docs-agent` — checkout main directly; no worktree needed.
- **Consumer work** happens in the consumer's existing main checkout (`/Users/theo/Projects/claude-code-self-assessment` or wherever it lives). **Do NOT** use the stale worktree at `/Users/theo/Projects/claude-extensions/.claude/worktrees/engineering-docs-agent-integration` — its branch was merged and the worktree itself needs separate removal from its parent checkout. If you can't find the consumer main checkout, run `git worktree list` from any clone of the consumer repo to locate it.
- **Use absolute paths** in every command per the consumer's CLAUDE.md convention.
- **Jira writes are per-action** under the user's auto-mode policy — each `createJiraIssue`, `addCommentToJiraIssue`, and `transitionJiraIssue` needs its own approval. Pause for direction when you reach those steps.

---

## Phase 0 — Pre-flight

### Task 0a: File the CCE ticket

**Files:** None (Jira API call only).

- [ ] **Step 1: Pause and ask the user for explicit per-action approval to file CCE-XX.**

The user's CLAUDE.md is explicit: "Auto-mode authorization for Jira writes is scoped per action, not per session." Do not auto-file.

Show the user the proposed ticket:

```
Summary:  fix(pages): bootstrap host Pages via gh api instead of misleading configure-pages enablement:true
Type:     Bug
Project:  CCE
```

Body (markdown):

```markdown
## Why

`theoju/claude-code-self-assessment` PR #121 / CCE-81 shipped the mkdocs upgrade. First push-triggered run of `docs-agent-pages.yml` after merge failed at `actions/configure-pages@v6` with `Resource not accessible by integration` — the workflow's `GITHUB_TOKEN` lacks admin scope to create a Pages site, and `permissions:` blocks can only restrict default-token scopes, never expand them. The `enablement: true` field is a no-op on first deploy (when it would matter) and a no-op every subsequent run (when Pages already exists).

The misleading line ships from `theoju/engineering-docs-agent` (this plugin) to every future `framework: mkdocs` host. Every new host hits the same first-deploy failure until we fix it here. Plus the plugin's own dogfood mkdocs site (`docs-pages.yml`) carries the same line.

## What

Spec: `/Users/theo/Projects/engineering-docs-agent/docs/superpowers/specs/2026-06-02-pages-bootstrap-design.md`

Two PRs (one per repo, independent ship order):

- **PR #B (plugin):** new `scripts/enable_pages.py` (wraps `gh api -X POST repos/.../pages -f build_type=workflow` with 4 failure modes); SKILL.md step 6c calls it; templates cleaned; existing test flipped; plugin's own dogfood `docs-pages.yml` cleaned; CLAUDE.md + CHANGELOG updated.
- **PR #A (consumer drive-by, ~13 LOC):** mirror the workflow + test fix in `theoju/claude-code-self-assessment`; one-line resolution footer on the existing POST-IMPLEMENTATION CORRECTION block.

## Acceptance

- Both PRs merged.
- Plugin pytest passes including 9 new test cases.
- Consumer `npm test` passes (689/689) with the flipped assertion.
- Plugin's CHANGELOG `[Unreleased]` entry present.
- This ticket transitions to Done after both PRs merge.

## Originating

- Incident: `theoju/claude-code-self-assessment` PR #121 / CCE-81 (2026-06-02)
- Corrections: `theoju/claude-code-self-assessment` PR #122 (2026-06-02)
```

- [ ] **Step 2: After user approval, file via Atlassian MCP.**

```
mcp__plugin_atlassian_atlassian__createJiraIssue(
  cloudId="f375676f-949f-4187-8adf-c9e6bbdb8458",
  projectKey="CCE",
  issueTypeName="Bug",
  summary="fix(pages): bootstrap host Pages via gh api instead of misleading configure-pages enablement:true",
  contentFormat="markdown",
  description="<the body above>"
)
```

- [ ] **Step 3: Record the returned ticket key.**

The returned `key` (e.g., `CCE-82`) is THE ticket key for this work. Every subsequent commit message, PR title, comment must use it verbatim — substitute it everywhere this plan says `CCE-XX`.

Expected output: `{"id":"...","key":"CCE-NN","self":"..."}`. Note the `key`.

### Task 0b: Create the plugin feature branch

**Files:** None (git only).

- [ ] **Step 1: Confirm clean working tree.**

Run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
git status --short
```

Expected: empty output (no uncommitted changes). If not empty: stash or commit before proceeding.

- [ ] **Step 2: Sync main from origin.**

Run:

```bash
git -C /Users/theo/Projects/engineering-docs-agent fetch origin main
git -C /Users/theo/Projects/engineering-docs-agent checkout main
git -C /Users/theo/Projects/engineering-docs-agent merge --ff-only origin/main
```

Expected: `Already up to date.` or a fast-forward summary.

- [ ] **Step 3: Create the feature branch from main.**

Substitute the real CCE key from Task 0a Step 3 for `CCE-XX` in the branch name. (Plugin CLAUDE.md branch convention: `<type>/CCE-<number>-<short-slug>`.)

Run:

```bash
git -C /Users/theo/Projects/engineering-docs-agent checkout -b fix/CCE-XX-pages-bootstrap
```

Expected: `Switched to a new branch 'fix/CCE-XX-pages-bootstrap'`.

---

## Phase 1 — Plugin TDD red: write failing tests first

### Task 1: Flip the existing template test from positive to negative + add structural guard (B0)

**Files:**

- Modify: `/Users/theo/Projects/engineering-docs-agent/tests/ci/test_workflow_pages_template.py` (existing test at line 30 currently asserts `assert "enablement: true" in text`)

- [ ] **Step 1: Read the current test file to confirm pre-state.**

Run:

```bash
cat -n /Users/theo/Projects/engineering-docs-agent/tests/ci/test_workflow_pages_template.py
```

Expected line 30: `    assert "enablement: true" in text`.

- [ ] **Step 2: Modify the test function `test_enablement_and_nojekyll_and_no_jekyll_build` to assert ABSENCE with an anchored regex.**

Edit the file. Replace this block (currently lines 28-33):

```python
def test_enablement_and_nojekyll_and_no_jekyll_build():
    text = TPL.read_text()
    assert "enablement: true" in text
    assert ".nojekyll" in text
    # The only acceptable "jekyll" is the .nojekyll marker; no legacy Jekyll.
    assert text.lower().replace(".nojekyll", "").find("jekyll") == -1
```

With:

```python
def test_enablement_field_is_absent_and_nojekyll_marker_present():
    """Regression guard: enablement: true is misleading (no-op on first
    deploy because the workflow token lacks admin scope; no-op forever
    after Pages exists). Pages bootstrap is done by scripts/enable_pages.py
    from SKILL.md step 6c using the operator's admin gh auth. See CCE-XX."""
    import re
    text = TPL.read_text()
    assert not re.search(
        r"^\s*enablement:\s*['\"]?true['\"]?\s*$",
        text,
        re.MULTILINE,
    ), (
        "templates/workflow-pages.yml must not carry `enablement: true` in "
        "any form (quoted, unquoted, leading whitespace) — see CCE-XX."
    )
    assert ".nojekyll" in text
    # The only acceptable "jekyll" is the .nojekyll marker; no legacy Jekyll.
    assert text.lower().replace(".nojekyll", "").find("jekyll") == -1
```

Substitute the real CCE key everywhere `CCE-XX` appears.

- [ ] **Step 3: Add a NEW structural test below it.**

Append (after `test_enablement_field_is_absent_and_nojekyll_marker_present`, before `test_default_build_workflow_filename_is_the_scaffold_target`):

```python
def test_configure_pages_step_has_no_with_block():
    """Structural guard against re-adding any `with:` block to configure-pages@v6.

    Currently no host configuration requires one. If a future change adds
    one, this test forces the maintainer to update both the test and the
    SKILL/CLAUDE.md documentation that explains WHY the field shouldn't
    be there. See CCE-XX."""
    data = yaml.safe_load(TPL.read_text())
    build_steps = data["jobs"]["build"]["steps"]
    cp_step = next(
        s for s in build_steps if s.get("uses", "").startswith("actions/configure-pages@")
    )
    assert "with" not in cp_step, (
        f"configure-pages step must not carry a `with:` block; "
        f"found: {cp_step.get('with')}. See CCE-XX."
    )
```

- [ ] **Step 4: Run the test suite to see them FAIL (TDD red).**

Run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
python3 -m pytest tests/ci/test_workflow_pages_template.py -v
```

Expected: `test_enablement_field_is_absent_and_nojekyll_marker_present` FAILS (template still has `enablement: true`); `test_configure_pages_step_has_no_with_block` FAILS (`with:` block still present); other tests pass.

The failure messages should reference `CCE-XX`.

- [ ] **Step 5: Commit the red tests.**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add tests/ci/test_workflow_pages_template.py
git commit -m "test(pages): flip template test to negative + add structural guard (red) — CCE-XX"
```

### Task 2: Write the new CLI test file with all 9 test cases (B5)

**Files:**

- Create: `/Users/theo/Projects/engineering-docs-agent/tests/ci/test_enable_pages_cli.py`

- [ ] **Step 1: Create the file with the imports + helpers.**

Write the file (entire content):

```python
"""Behavioral coverage of scripts/enable_pages.py — all four failure-mode
branches plus the substring-false-positive risk and the argv contract.

The test installs a `gh` stub in tmp_path/bin and PATH-shadows the real
binary. Real gh exits 1 on all HTTP 4xx (not 4 or 22 — those would be
curl-style codes); the stub mimics this. Each stub also writes its argv
to a side-channel file so the test can assert the script invokes gh with
the expected `repos/<owner>/<repo>/pages` path + `build_type=workflow`
form-field. Without that argv assertion a future refactor swapping owner
and repo would pass every other test.

Reference: CCE-XX. See SKILL.md step 6c and scripts/enable_pages.py."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "enable_pages.py"


def _install_gh_stub(
    bin_dir: Path,
    exit_code: int,
    stdout: str,
    stderr: str,
    argv_capture: Path | None = None,
) -> None:
    """Write a shell script named `gh` that exits with the given code/output.

    If argv_capture is set, the stub writes its full argv to that file so
    tests can assert the script invoked gh with the expected arguments.

    The stderr in real gh follows `gh: <message> (HTTP <code>)` — tests
    that simulate HTTP errors should include the literal `(HTTP NNN)`
    substring in `stderr` to match the script's detection logic.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "gh"
    capture = f'printf "%s\\n" "$@" > {argv_capture}\n' if argv_capture else ""
    stub.write_text(
        f"#!/bin/sh\n"
        f"{capture}"
        f"cat >&2 <<'STDERR_EOF'\n{stderr}\nSTDERR_EOF\n"
        f"cat <<'STDOUT_EOF'\n{stdout}\nSTDOUT_EOF\n"
        f"exit {exit_code}\n"
    )
    stub.chmod(0o755)


def _run_cli(
    bin_dir: Path,
    owner: str = "octocat",
    repo: str = "sample",
) -> subprocess.CompletedProcess:
    """Run scripts/enable_pages.py with PATH containing only the stub dir
    (plus the inherited PATH appended). This is per-process so it survives
    pytest-xdist if that's ever added to the suite."""
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    return subprocess.run(
        [sys.executable, str(_CLI), "--owner", owner, "--repo", repo],
        capture_output=True,
        text=True,
        env=env,
    )
```

(Continued in next step — this file gets its 9 test functions.)

- [ ] **Step 2: Add test case 1 — happy path 201.**

Append:

```python


# --- Happy path ---


def test_happy_path_201_prints_success_and_returns_zero(tmp_path):
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=0,
        stdout='{"html_url":"https://octocat.github.io/sample/","build_type":"workflow"}',
        stderr="",
    )
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0, proc.stderr
    assert "✓ Pages enabled" in proc.stdout
    assert "octocat.github.io/sample" in proc.stdout
```

- [ ] **Step 3: Add test case 2 — argv contract (highest-leverage hardening).**

Append:

```python


def test_argv_carries_correct_path_and_build_type(tmp_path):
    """Highest-leverage hardening: a future refactor that swaps owner/repo
    or drops `-f build_type=workflow` would still pass every other test
    because the stub ignores argv. This test asserts gh was called with
    the right path components and the build_type form-field."""
    argv_file = tmp_path / "gh.argv"
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=0,
        stdout='{"html_url":"x"}',
        stderr="",
        argv_capture=argv_file,
    )
    _run_cli(tmp_path / "bin", owner="my-org", repo="some-repo")
    argv = argv_file.read_text().splitlines()
    # ["api", "-X", "POST", "repos/my-org/some-repo/pages", "-f", "build_type=workflow"]
    assert "repos/my-org/some-repo/pages" in argv, f"argv was: {argv}"
    assert "build_type=workflow" in argv, f"argv was: {argv}"
    assert "POST" in argv
    assert "api" in argv
```

- [ ] **Step 4: Add test case 3 — 409 idempotent.**

Append:

```python


# --- 409 idempotent ---


def test_already_enabled_409_is_idempotent(tmp_path):
    # Real gh stderr format: "gh: <message> (HTTP 409)" — the literal
    # "(HTTP 409)" substring (with parens) is what the script matches.
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=1,  # gh exits 1 on HTTP 4xx regardless of HTTP code
        stdout="",
        stderr="gh: Pages site already created (HTTP 409)",
    )
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0
    assert "already enabled" in proc.stdout.lower()
    assert "⚠" not in proc.stdout  # not a warning path
```

- [ ] **Step 5: Add test case 4 — 409 substring false positive.**

Append:

```python


def test_409_substring_false_positive_is_not_classified_as_idempotent(tmp_path):
    """A 500 whose error body QUOTES `HTTP 409` (or contains the bare
    phrase `already exists` in unrelated prose) must NOT be classified
    as idempotent. The script uses re.search(r"\\(HTTP 409\\)", stderr) —
    literal parens, so this 500 reaches the graceful-fallback branch."""
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=1,
        stdout="",
        stderr="gh: Internal Server Error: previous request returned HTTP 409 - not retried (HTTP 500)",
    )
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0
    assert "already enabled" not in proc.stdout.lower(), proc.stdout
    assert "⚠ Could not enable" in proc.stdout
```

- [ ] **Step 6: Add the parametrized fallback test (6 sub-cases).**

Append:

```python


# --- Fallback path (all non-201/409 cases collapse to graceful fallback) ---


@pytest.mark.parametrize(
    "exit_code,stderr",
    [
        (1, "gh: Resource not accessible by integration (HTTP 403)"),
        (1, "gh: Unauthorized (HTTP 401)"),
        (1, "gh: Validation failed (HTTP 422)"),
        (1, "gh: Internal Server Error (HTTP 500)"),
        (139, ""),  # segfault — empty stderr
        (0, ""),    # exit 0 but empty body — could be proxy interception
    ],
    ids=["403_auth", "401_unauth", "422_validation", "500_server", "139_segfault", "0_empty_body"],
)
def test_all_non_201_non_409_paths_fall_back_gracefully(tmp_path, exit_code, stderr):
    _install_gh_stub(tmp_path / "bin", exit_code=exit_code, stdout="", stderr=stderr)
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0, "must never block scaffolding"
    assert "⚠ Could not enable Pages" in proc.stdout
    assert "gh api -X POST repos/octocat/sample/pages -f build_type=workflow" in proc.stdout
    assert "Continuing" in proc.stdout
```

- [ ] **Step 7: Add test case for gh missing.**

Append:

```python


# --- gh missing ---


def test_gh_missing_prints_recovery_and_returns_zero(tmp_path):
    # PATH intentionally empty-except-for-stub-dir to force shutil.which('gh') -> None
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env = os.environ.copy()
    env["PATH"] = str(empty_bin)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--owner", "octocat", "--repo", "sample"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    assert "`gh` CLI not found" in proc.stdout
    assert "gh api -X POST repos/octocat/sample/pages" in proc.stdout
```

- [ ] **Step 8: Add argparse boundary tests.**

Append:

```python


# --- Argparse boundary ---


def test_missing_args_returns_nonzero(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(_CLI)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    # argparse default is exit 2 on missing required
    assert "owner" in proc.stderr.lower() or "owner" in proc.stdout.lower()


def test_empty_owner_or_repo_rejected_with_exit_2(tmp_path):
    """argparse `required=True` only guards missingness, not empty strings.
    The script rejects empty strings explicitly, otherwise it would POST
    to `repos//<repo>/pages` and confuse gh."""
    for args in [["--owner", "", "--repo", "x"], ["--owner", "x", "--repo", ""]]:
        proc = subprocess.run(
            [sys.executable, str(_CLI), *args],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2, (
            f"expected exit 2 for empty owner/repo, args={args}, got {proc.returncode}"
        )
```

- [ ] **Step 9: Add hyphen-in-argv cosmetic test.**

Append:

```python


# --- Argparse cosmetics ---


def test_owner_with_hyphen_works(tmp_path):
    """argparse handles hyphens in values fine; pin the contract so a
    future refactor that adds a stripping step would break this test."""
    argv_file = tmp_path / "gh.argv"
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=0,
        stdout='{"html_url":"x"}',
        stderr="",
        argv_capture=argv_file,
    )
    proc = _run_cli(
        tmp_path / "bin",
        owner="my-cool-org-name",
        repo="repo-with-dashes",
    )
    assert proc.returncode == 0
    argv = argv_file.read_text().splitlines()
    assert "repos/my-cool-org-name/repo-with-dashes/pages" in argv
```

Substitute the real CCE key everywhere `CCE-XX` appears in the docstrings.

- [ ] **Step 10: Run the new test file to see it ALL fail (TDD red).**

Run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
python3 -m pytest tests/ci/test_enable_pages_cli.py -v
```

Expected: every test fails. The most likely failure is the very early one — pytest can't import / find the CLI at `scripts/enable_pages.py` because it doesn't exist yet. That's the red state.

- [ ] **Step 11: Commit the red tests.**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add tests/ci/test_enable_pages_cli.py
git commit -m "test(pages): add enable_pages CLI behavioral suite (red, 9 cases) — CCE-XX"
```

---

## Phase 2 — Plugin TDD green: make the tests pass

### Task 3: Create the `enable_pages.py` script (B2)

**Files:**

- Create: `/Users/theo/Projects/engineering-docs-agent/scripts/enable_pages.py`

- [ ] **Step 1: Create the script.**

Write the file (entire content):

```python
#!/usr/bin/env python3
"""Bootstrap GitHub Pages on a host repo with build_type=workflow.

The setup skill's step 6c calls this once during scaffolding because
actions/configure-pages@v6 with `enablement: true` does NOT actually
work on first deploy — the workflow's GITHUB_TOKEN lacks admin scope
to create a Pages site (`permissions:` blocks can only restrict
default-token scopes, never expand them). The user's admin `gh` auth
does have the required scope.

Behaviors (all return exit 0 — scaffolding must never block on this):
  201 + non-empty JSON body: print "✓ Pages enabled", return 0.
  409 (matched by literal "(HTTP 409)" in stderr, not bare substring):
      print "✓ Pages already enabled (idempotent)", return 0.
  gh not on PATH: print "⚠ `gh` CLI not found" + manual recovery,
      return 0.
  Any other failure (401, 403, 422, 500, exit 139, exit 0 with empty
      body, etc.): print "⚠ Could not enable Pages" + manual recovery
      + the actual error, return 0.

Exit codes:
  0: any of the above behaviors completed.
  2: argument or environment error (missing/empty --owner/--repo).

Reference: CCE-XX. See skills/engineering-docs-agent-setup/SKILL.md
step 6c."""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys


_RECOVERY_TEMPLATE = (
    "    gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow"
)


def enable_pages(owner: str, repo: str) -> int:
    if not owner or not repo:
        print(
            "✗ --owner and --repo must both be non-empty.",
            file=sys.stderr,
        )
        return 2
    if shutil.which("gh") is None:
        print(
            "⚠ `gh` CLI not found on PATH. Pages must be enabled manually before "
            "first deploy:\n"
            + _RECOVERY_TEMPLATE.format(owner=owner, repo=repo)
            + "\nContinuing with the rest of scaffolding."
        )
        return 0
    proc = subprocess.run(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{owner}/{repo}/pages",
            "-f",
            "build_type=workflow",
        ],
        capture_output=True,
        text=True,
    )
    # Detect 409 with literal "(HTTP 409)" — matches gh's actual stderr format
    # "gh: ... (HTTP 409)" and avoids false positives from JSON bodies
    # containing `"status":"409"` or prose containing `"already exists"`.
    is_409 = bool(re.search(r"\(HTTP 409\)", proc.stderr))
    if proc.returncode == 0 and proc.stdout.strip():
        # Real Pages creation returns a JSON body with html_url; require
        # non-empty so a network-glitched empty-body exit-0 doesn't
        # false-positive as success.
        print(f"✓ Pages enabled (https://{owner}.github.io/{repo}/)")
        return 0
    if is_409:
        print("✓ Pages already enabled (idempotent)")
        return 0
    err_summary = (proc.stderr or proc.stdout or "(no output)").strip()[:300]
    print(
        "⚠ Could not enable Pages programmatically. Run this manually before first deploy:\n"
        + _RECOVERY_TEMPLATE.format(owner=owner, repo=repo)
        + f"\n(gh exit {proc.returncode}; error: {err_summary})\n"
        + "Continuing with the rest of scaffolding."
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bootstrap GitHub Pages on a host repo with build_type=workflow."
    )
    p.add_argument("--owner", required=True, help="GitHub owner (user or org).")
    p.add_argument("--repo", required=True, help="Repository name.")
    args = p.parse_args()
    return enable_pages(args.owner, args.repo)


if __name__ == "__main__":
    sys.exit(main())
```

Substitute the real CCE key for `CCE-XX` in the module docstring.

- [ ] **Step 2: Make the script executable.**

Run:

```bash
chmod +x /Users/theo/Projects/engineering-docs-agent/scripts/enable_pages.py
```

- [ ] **Step 3: Run the new test file to see them ALL pass (TDD green).**

Run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
python3 -m pytest tests/ci/test_enable_pages_cli.py -v
```

Expected: 9 distinct test functions × the parametrized 6 cases for the fallback test = 14 test instances total, all pass.

Exact expected output line count: 14 PASSED, 0 failed.

- [ ] **Step 4: Run the full plugin pytest suite to confirm no regressions.**

Run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
python3 -m pytest tests/ -v
```

Expected: all previously-passing tests still pass; the 2 failing template tests from Task 1 are still failing (B1 fixes them next); the 14 new CLI tests all pass.

- [ ] **Step 5: Commit.**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add scripts/enable_pages.py
git commit -m "feat(pages): add scripts/enable_pages.py — gh api Pages bootstrap with 4 failure modes — CCE-XX"
```

### Task 4: Delete `enablement: true` from the plugin template (B1)

**Files:**

- Modify: `/Users/theo/Projects/engineering-docs-agent/templates/workflow-pages.yml`

- [ ] **Step 1: Read the template to confirm pre-state and find exact line numbers.**

Run:

```bash
grep -n "configure-pages\|enablement" /Users/theo/Projects/engineering-docs-agent/templates/workflow-pages.yml
```

Expected: matches at the `uses:` line and the `enablement: true` line, with `with:` immediately above. (Per spec, around lines 30-32.)

- [ ] **Step 2: Edit the template — delete the `with:` block.**

Use Edit tool to replace:

```yaml
- uses: actions/configure-pages@v6
  with:
    enablement: true
```

With:

```yaml
- uses: actions/configure-pages@v6
```

Note: indentation is significant — preserve the 6-space leading whitespace before `- uses:` exactly.

- [ ] **Step 3: Run the template tests to see them now PASS (TDD green).**

Run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
python3 -m pytest tests/ci/test_workflow_pages_template.py -v
```

Expected: all 4 tests pass (including the flipped `test_enablement_field_is_absent_and_nojekyll_marker_present` and the new `test_configure_pages_step_has_no_with_block`).

- [ ] **Step 4: Run the full suite once more to confirm no other tests regressed.**

Run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
python3 -m pytest tests/ -v
```

Expected: full suite passes.

- [ ] **Step 5: Commit.**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add templates/workflow-pages.yml
git commit -m "fix(pages): drop misleading enablement: true from templates/workflow-pages.yml — CCE-XX"
```

### Task 5: Delete `enablement: true` from the plugin's own dogfood Pages workflow (B6)

**Files:**

- Modify: `/Users/theo/Projects/engineering-docs-agent/.github/workflows/docs-pages.yml`

- [ ] **Step 1: Read the dogfood workflow to confirm pre-state.**

Run:

```bash
cat -n /Users/theo/Projects/engineering-docs-agent/.github/workflows/docs-pages.yml | head -30
```

Expected lines 23-25:

```
    23  - uses: actions/configure-pages@v6
    24    with:
    25      enablement: true
```

- [ ] **Step 2: Edit the dogfood workflow — same delete.**

Use Edit tool to replace:

```yaml
- uses: actions/configure-pages@v6
  with:
    enablement: true
```

With:

```yaml
- uses: actions/configure-pages@v6
```

- [ ] **Step 3: Confirm no test asserts on this file's content.**

Run:

```bash
grep -rn "docs-pages.yml" /Users/theo/Projects/engineering-docs-agent/tests/ 2>&1 | grep -v __pycache__
```

Expected: no matches (the test in `tests/ci/test_workflow_pages_template.py` targets `templates/workflow-pages.yml`, not the actual deployed `.github/workflows/docs-pages.yml`).

- [ ] **Step 4: Run the full suite to confirm no incidental breakage.**

Run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
python3 -m pytest tests/ -v
```

Expected: full suite passes.

- [ ] **Step 5: Commit.**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add .github/workflows/docs-pages.yml
git commit -m "fix(pages): drop misleading enablement: true from plugin's dogfood docs-pages.yml — CCE-XX"
```

---

## Phase 3 — Plugin documentation

### Task 6: Update SKILL.md step 6a + add step 6c (B3)

**Files:**

- Modify: `/Users/theo/Projects/engineering-docs-agent/skills/engineering-docs-agent-setup/SKILL.md`

- [ ] **Step 1: Find the exact location of the wrong claim sentence in step 6a.**

Run:

```bash
grep -n "configure-pages(enablement:true)" /Users/theo/Projects/engineering-docs-agent/skills/engineering-docs-agent-setup/SKILL.md
```

Expected: exactly one match in step 6a. Note the line number for the Edit.

- [ ] **Step 2: Replace the wrong claim sentence in step 6a.**

Use Edit tool to replace this exact string:

```
`configure-pages(enablement:true)` sets the repo's Pages source to GitHub Actions on first run.
```

With:

```
`configure-pages` is invoked without `enablement: true` — that field is misleading (it's a no-op on first deploy because the workflow's `GITHUB_TOKEN` lacks admin scope, despite `permissions: pages: write` being declared). Pages bootstrap happens via step 6c's `gh api` call using the operator's admin auth. `configure-pages` here only sets the deploy env var consumed by `deploy-pages@v5`.
```

- [ ] **Step 3: Find where to insert the new step 6c (after 6b, before step 7).**

Run:

```bash
grep -n "^   6a\|^   6b\|^7\." /Users/theo/Projects/engineering-docs-agent/skills/engineering-docs-agent-setup/SKILL.md
```

Note the line numbers. Step 6c goes between the end of step 6b and the start of step 7. If step 6b's text ends at line N and step 7 starts at line M, insert 6c on a new line between them.

- [ ] **Step 4: Insert the new step 6c.**

Use Edit tool. Find the last line of step 6b (the line ending step 6b's prose, typically `... no operator-visible diff churn.`) and add the new step 6c after it. The exact text to add:

````markdown
6c. **Bootstrap GitHub Pages** for the host repo. SKIP this step if 6a did NOT write `docs-agent-pages.yml` (i.e., non-MkDocs host without `publishing.build_command`).

Pages must exist with `build_type=workflow` before the first push-triggered run of `docs-agent-pages.yml` will succeed. The setup skill performs this once during scaffolding using the user's admin `gh` auth (the workflow token lacks the required scope — see 6a). Reuse the `$OWNER`/`$REPO` resolved in step 6b (`discovery["git"]["owner"]` / `discovery["git"]["repo"]`, with `AskUserQuestion` fallback if `discovery["git"]` is `None`).

Run:

```bash
python <plugin_root>/scripts/enable_pages.py --owner "$OWNER" --repo "$REPO"
```
````

The script handles four cases and always returns 0 (never blocks scaffolding):

- **HTTP 201 (happy path):** prints `✓ Pages enabled (https://$OWNER.github.io/$REPO/)`.
- **HTTP 409 (already enabled):** prints `✓ Pages already enabled (idempotent)`. Safe on re-run.
- **`gh` not installed/on PATH:** prints `⚠ `gh` CLI not found` + the manual recovery command. The user runs the command after `gh auth login`.
- **Any other failure:** prints `⚠ Could not enable Pages` + the manual recovery command + the actual gh error. See CCE-XX for the full rationale.

````

Substitute the real CCE key for `CCE-XX`.

- [ ] **Step 5: Verify the SKILL.md still parses cleanly.**

Run:
```bash
grep -n "^6c\.\|^   6c\.\|^6c " /Users/theo/Projects/engineering-docs-agent/skills/engineering-docs-agent-setup/SKILL.md
````

Expected: one match for the new step 6c.

- [ ] **Step 6: Run the plugin pytest to confirm no skill-shape tests broke.**

Run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
python3 -m pytest tests/ -v
```

Expected: full suite passes.

- [ ] **Step 7: Commit.**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add skills/engineering-docs-agent-setup/SKILL.md
git commit -m "docs(pages): SKILL.md — fix step 6a wrong claim + add step 6c Pages bootstrap — CCE-XX"
```

### Task 7: Add CLAUDE.md convention bullet (B4)

**Files:**

- Modify: `/Users/theo/Projects/engineering-docs-agent/CLAUDE.md`

- [ ] **Step 1: Read the existing CLAUDE.md structure to find the right home for the new bullet.**

Run:

```bash
grep -n "^## " /Users/theo/Projects/engineering-docs-agent/CLAUDE.md
```

Find the "Plugin conventions" section (per spec exploration, exists in the plugin's CLAUDE.md).

- [ ] **Step 2: Insert the new bullet at the end of "Plugin conventions" section.**

Use Edit tool to add this bullet at the end of the Plugin conventions list (find the last `- ` bullet in that section, add after it):

```markdown
- **`actions/configure-pages@v6 enablement: true` does NOT bootstrap GitHub Pages on a first deploy.** Despite the field name and the action's docs. The workflow's `GITHUB_TOKEN` lacks the admin scope required to call `POST /repos/.../pages`; `permissions:` blocks can only restrict default-token scopes, never expand them. The plugin's `templates/workflow-pages.yml` therefore does NOT include this field; bootstrap is done by `skills/engineering-docs-agent-setup` step 6c calling `scripts/enable_pages.py` (which wraps `gh api -X POST repos/.../pages -f build_type=workflow`) with the operator's admin gh auth. The script handles 4 failure modes (201, 409, gh-missing, all-other) and always returns 0 — graceful fallback never blocks scaffolding. Reference: CCE-XX (2026-06-02); the originating incident was `theoju/claude-code-self-assessment` PR #121 / CCE-81. The plugin's own dogfood `.github/workflows/docs-pages.yml` was also cleaned in this fix.
```

Substitute the real CCE key for `CCE-XX`.

- [ ] **Step 3: Commit.**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add CLAUDE.md
git commit -m "docs(pages): CLAUDE.md — add Pages enablement convention bullet — CCE-XX"
```

### Task 8: Add CHANGELOG.md entry (B7)

**Files:**

- Modify: `/Users/theo/Projects/engineering-docs-agent/CHANGELOG.md`

- [ ] **Step 1: Read the CHANGELOG to find the Unreleased section.**

Run:

```bash
head -50 /Users/theo/Projects/engineering-docs-agent/CHANGELOG.md
```

Find the `## [Unreleased]` header. If there's no Unreleased section, add one above the most-recent versioned entry.

- [ ] **Step 2: Add the Fixed entry to `[Unreleased]`.**

Use Edit tool. If `[Unreleased]` exists with a `### Fixed` subsection, append the bullet to that subsection. If `[Unreleased]` exists without `### Fixed`, add the subsection. If `[Unreleased]` doesn't exist, add the whole header above the most-recent versioned entry.

The bullet text:

```markdown
- **Pages bootstrap on first host deploy.** Replaced `actions/configure-pages@v6 enablement: true` (a no-op on first deploy because the workflow's `GITHUB_TOKEN` lacks admin scope) with a setup-time `gh api -X POST repos/.../pages -f build_type=workflow` call from the new `scripts/enable_pages.py`. The setup skill's step 6c invokes it after writing the docs-pages workflow. Graceful fallback on all error paths — scaffolding never blocks on Pages bootstrap. Originating incident: `theoju/claude-code-self-assessment` PR #121 / CCE-81. Tracker: CCE-XX.
```

Substitute the real CCE key for `CCE-XX`.

- [ ] **Step 3: Commit.**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add CHANGELOG.md
git commit -m "docs(pages): CHANGELOG — record Pages bootstrap fix in Unreleased — CCE-XX"
```

---

## Phase 4 — Plugin PR ship

### Task 9: Open the plugin PR (PR #B)

**Files:** None (git + gh only).

- [ ] **Step 1: Final pre-flight check — confirm green local state.**

Run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
python3 -m pytest tests/ -v
```

Expected: all tests pass.

```bash
git -C /Users/theo/Projects/engineering-docs-agent log --oneline origin/main..HEAD
```

Expected: 8 commits ahead (one per task above, except 0a/0b which made no commits).

- [ ] **Step 2: Push the branch.**

```bash
git -C /Users/theo/Projects/engineering-docs-agent push -u origin fix/CCE-XX-pages-bootstrap
```

Substitute the real CCE key. Expected: branch created at origin; `gh` reports the PR-create URL.

- [ ] **Step 3: Write the PR body to a file.**

Avoid heredoc in `gh pr create` per the consumer CLAUDE.md "block-destructive scans literal command text" convention. Write to `/tmp/pr-body-plugin-bootstrap.md`:

```markdown
## Summary

Replaces the misleading `actions/configure-pages@v6 enablement: true` (a no-op on first deploy — the workflow's `GITHUB_TOKEN` lacks admin scope) with a setup-time `gh api -X POST repos/.../pages -f build_type=workflow` call from the new `scripts/enable_pages.py`. The setup skill's step 6c invokes it after writing the docs-pages workflow. Graceful fallback on all error paths — scaffolding never blocks on Pages bootstrap.

**8 commits, ~355 LOC across 8 files.** See spec `/docs/superpowers/specs/2026-06-02-pages-bootstrap-design.md` for full design rationale + the 3-agent verification findings + how they reshaped the spec.

### What's in this PR

- **New `scripts/enable_pages.py`** (~95 lines) wraps `gh api` with 4 failure-mode behaviors (201 happy / 409 idempotent / gh-missing / all-other-graceful). All paths return exit 0 — scaffolding never blocks. Tightened 409 detection uses literal `(HTTP 409)` regex to avoid false positives on 500s that happen to quote "HTTP 409" in their body.
- **`templates/workflow-pages.yml`** — dropped misleading `with: enablement: true` block (3 lines).
- **`.github/workflows/docs-pages.yml` (this repo's own dogfood)** — same cleanup; Pages was bootstrapped on first-ever deploy weeks ago so this is a pure no-op clean.
- **`skills/engineering-docs-agent-setup/SKILL.md`** — step 6a rewrite (the previous "configure-pages(enablement:true) sets the source on first run" claim was verbatim wrong); new step 6c calls `enable_pages.py` after writing the workflow file.
- **`tests/ci/test_workflow_pages_template.py`** — flipped the positive `assert "enablement: true" in text` to a negative anchored-regex assertion + added a structural test that asserts no `with:` block ever returns to `configure-pages@v6` (catches re-add via any variant).
- **`tests/ci/test_enable_pages_cli.py` (NEW)** — 9 test cases covering happy path, argv contract (highest-leverage hardening — catches future owner/repo swap or `build_type` drop), 409 idempotency, 409-substring-false-positive (a 500 quoting "HTTP 409" in its body must NOT be classified as idempotent), 6 parametrized fallback cases (403/401/422/500/exit-139/exit-0-with-empty-body), gh-missing, missing-args, empty-args, hyphen-in-args.
- **`CLAUDE.md`** + **`CHANGELOG.md`** — convention bullet + Unreleased Fixed entry.

## Why

`theoju/claude-code-self-assessment` PR #121 / CCE-81 hit the first-deploy failure during its mkdocs upgrade rollout. Recovery required manual `gh api`; root cause was traced to the misleading `enablement: true` field which the plugin's template + setup skill ship to every future host. This PR closes the bug at the source.

## Test plan

- [x] `python3 -m pytest tests/ -v` — full suite passes locally (existing + 4 flipped/added template tests + 14 new CLI tests = 18 new test instances)
- [x] Pre-execution spec validated by 3 independent agents (correctness/completeness/test-rigor); all findings addressed and recorded in spec "Validation findings & responses"
- [ ] **Post-merge:** plugin's own `docs-pages.yml` re-fires on the squash commit; Pages site continues serving (no behavior change for already-bootstrapped sites)
- [ ] **Future:** next new host onboarded with `framework: mkdocs` via the setup skill bootstraps Pages cleanly without manual `gh api` (covered by Future Work §3 integration smoke harness)

## Rollback

Single `git revert` of the squash-merge commit. No production impact on existing hosts (template + script + skill consumed only by NEW setup runs). Plugin's own site continues serving regardless.

## Linked work

- **Ticket:** [CCE-XX](https://designitright.atlassian.net/browse/CCE-XX)
- **Spec:** `docs/superpowers/specs/2026-06-02-pages-bootstrap-design.md`
- **Originating incident:** `theoju/claude-code-self-assessment` PR #121 / CCE-81 (2026-06-02)
- **Consumer drive-by:** `theoju/claude-code-self-assessment` PR #A (forthcoming)

---

Generated with [Claude Code](https://claude.com/claude-code)
```

Substitute the real CCE key everywhere `CCE-XX` appears. Also substitute the real consumer PR number for `PR #A` if it has been filed before this PR; otherwise leave `(forthcoming)`.

- [ ] **Step 4: Open the PR.**

```bash
gh pr create \
  --repo theoju/engineering-docs-agent \
  --base main \
  --title "fix(pages): bootstrap host Pages via gh api — CCE-XX" \
  --body-file /tmp/pr-body-plugin-bootstrap.md
```

Substitute the real CCE key. Expected: returns the PR URL.

- [ ] **Step 5: Wait for plugin CI to pass.**

Run:

```bash
gh pr checks <PR#> --repo theoju/engineering-docs-agent
```

Expected: all checks pass (actionlint, yaml-lint, pytest, whatever else the plugin's CI runs).

- [ ] **Step 6: Pause — do NOT auto-merge.**

Wait for user direction before squash-merging. (Per consumer CLAUDE.md convention: PR merges to main are reviewer-gated; auto-mode does not extend to merges of code PRs.)

After user approves merge, run:

```bash
gh pr merge <PR#> --repo theoju/engineering-docs-agent --squash --subject "fix(pages): bootstrap host Pages via gh api — CCE-XX (#<PR#>)"
```

Then verify:

```bash
gh pr view <PR#> --repo theoju/engineering-docs-agent --json state,mergeCommit
```

Expected: `state: MERGED` + a `mergeCommit.oid`.

---

## Phase 5 — Consumer drive-by PR

### Task 10: Switch to the consumer's main checkout + create branch

**Files:** None (git only).

- [ ] **Step 1: Locate the consumer repo's main checkout.**

Run:

```bash
git worktree list 2>&1 || echo "run from any clone of theoju/claude-code-self-assessment"
```

If the consumer main checkout is at a known path (e.g., `~/Projects/claude-code-self-assessment`), use that. Otherwise, ask the user.

**Important:** do NOT use `/Users/theo/Projects/claude-extensions/.claude/worktrees/engineering-docs-agent-integration` — that's the stale worktree from PR #121's session whose branch was merged; its branch is gone. Use the consumer's REAL main checkout.

- [ ] **Step 2: Confirm clean working tree + sync main.**

Run (substituting the real path for `<consumer-main>`):

```bash
git -C <consumer-main> status --short
git -C <consumer-main> fetch origin main
git -C <consumer-main> checkout main
git -C <consumer-main> merge --ff-only origin/main
```

Expected: clean status, fast-forward to latest main.

- [ ] **Step 3: Create the feature branch.**

Run:

```bash
git -C <consumer-main> checkout -b fix/CCE-XX-pages-cleanup
```

Substitute the real CCE key. Expected: `Switched to a new branch 'fix/CCE-XX-pages-cleanup'`.

### Task 11: Clean consumer workflow — comments + with-block (A1)

**Files:**

- Modify: `<consumer-main>/.github/workflows/docs-agent-pages.yml`

- [ ] **Step 1: Read the file's current state.**

Run:

```bash
cat -n <consumer-main>/.github/workflows/docs-agent-pages.yml | head -40
```

Expected: comment block at lines 3-6 containing the wrong claim text (`"configure-pages@v6 with enablement: true / enables Pages programmatically on the first run."`), and a `with: enablement: true` block around lines 32-34 under `actions/configure-pages@v6`.

- [ ] **Step 2: Edit the comment block.**

Use Edit tool to replace:

```yaml
# Builds the mkdocs site and deploys to GitHub Pages.
# Fires only when docs sources actually change (path filter below) +
# manual workflow_dispatch. configure-pages@v6 with enablement: true
# enables Pages programmatically on the first run.
```

With:

```yaml
# Builds the mkdocs site and deploys to GitHub Pages.
# Fires only when docs sources actually change (path filter below) +
# manual workflow_dispatch.
```

- [ ] **Step 3: Edit the with-block.**

Use Edit tool to replace:

```yaml
- uses: actions/configure-pages@v6
  with:
    enablement: true
```

With:

```yaml
- uses: actions/configure-pages@v6
```

Preserve 6-space indentation before `- uses:` exactly.

- [ ] **Step 4: Verify the consumer's existing test would now FAIL on the workflow.**

Run:

```bash
cd <consumer-main>
npm run test:unit -- docs-mkdocs-scaffold 2>&1 | head -50
```

Expected: at least one assertion fails — specifically the `expect(body).toMatch(/enablement:\s*true/)` line at `scripts/__tests__/docs-mkdocs-scaffold.test.mjs:76` now fails (because the workflow no longer contains the line). This is the TDD red intermediate state — Task 12 fixes it.

- [ ] **Step 5: Stage the workflow file but do not commit yet.**

(Task 12 commits both files together as one atomic "fix-and-update-test" change.)

```bash
git -C <consumer-main> add .github/workflows/docs-agent-pages.yml
```

### Task 12: Flip the consumer test from positive to negative regression guard (A2)

**Files:**

- Modify: `<consumer-main>/scripts/__tests__/docs-mkdocs-scaffold.test.mjs` (line 76)

- [ ] **Step 1: Confirm pre-state.**

Run:

```bash
sed -n '74,78p' <consumer-main>/scripts/__tests__/docs-mkdocs-scaffold.test.mjs
```

Expected:

```javascript
expect(body).toMatch(/actions\/configure-pages@v6/);
expect(body).toMatch(/enablement:\s*true/);
expect(body).toMatch(/actions\/upload-pages-artifact@v5/);
```

- [ ] **Step 2: Replace line 76 with the negative + broader assertion.**

Use Edit tool to replace:

```javascript
expect(body).toMatch(/enablement:\s*true/);
```

With:

```javascript
expect(body).not.toMatch(/enablement:\s*['"]?true['"]?/);
```

The broader regex (`['"]?true['"]?`) matches `enablement: true`, `enablement: "true"`, `enablement: 'true'`, `enablement:true` — any quoted/unquoted variant. Aligned with the plugin's anchored regex in `tests/ci/test_workflow_pages_template.py`.

- [ ] **Step 3: Run the consumer's full test suite.**

Run:

```bash
cd <consumer-main>
npm test
```

Expected: 689/689 tests pass (the test count is unchanged; one test changed shape).

- [ ] **Step 4: Stage the test file and commit A1 + A2 together.**

```bash
git -C <consumer-main> add scripts/__tests__/docs-mkdocs-scaffold.test.mjs
git -C <consumer-main> commit -m "fix(pages): drop misleading enablement:true from workflow + flip test to negative — CCE-XX"
```

Substitute the real CCE key.

### Task 13: Annotate the PR #121 spec with a "Resolved by" footer (A3)

**Files:**

- Modify: `<consumer-main>/docs/superpowers/specs/2026-06-01-mkdocs-upgrade-design.md`

- [ ] **Step 1: Locate the end of the POST-IMPLEMENTATION CORRECTION block.**

Run:

```bash
grep -n "Conventions section now carries this gotcha for the project" <consumer-main>/docs/superpowers/specs/2026-06-01-mkdocs-upgrade-design.md
```

Expected: one match in the POST-IMPLEMENTATION CORRECTION block (around line 453).

- [ ] **Step 2: Append the one-line "Resolved by" footer to that block.**

Use Edit tool to replace:

```
> The CLAUDE.md
> Conventions section now carries this gotcha for the project.
```

With:

```
> The CLAUDE.md
> Conventions section now carries this gotcha for the project.
>
> **Resolved 2026-06-02 by PR #A (this repo) + PR #B (plugin) under CCE-XX:** template + this repo's workflow + plugin's own workflow all cleaned; bootstrap is now done by `scripts/enable_pages.py` from SKILL.md step 6c.
```

Substitute the real CCE key. Leave `PR #A` and `PR #B` as literal placeholders if PR numbers aren't yet known; substitute when both are filed.

- [ ] **Step 3: Commit.**

```bash
git -C <consumer-main> add docs/superpowers/specs/2026-06-01-mkdocs-upgrade-design.md
git -C <consumer-main> commit -m "docs(pages): annotate PR #121 spec with CCE-XX resolution footer — CCE-XX"
```

### Task 14: Shorten the consumer's CLAUDE.md Pages enablement bullet (A4)

**Files:**

- Modify: `<consumer-main>/CLAUDE.md` (around line 438)

- [ ] **Step 1: Find the exact anchor text.**

Run:

```bash
grep -n "The line should be deleted from the workflow to" <consumer-main>/CLAUDE.md
```

Expected: one match (around line 438, per the prior audit's verification).

- [ ] **Step 2: Replace the multi-line phrase.**

Use Edit tool to replace:

```
The line should be deleted from the workflow to
  remove the footgun; the post-implementation note in the spec
```

With:

```
The line was deleted from the workflow in PR #A / CCE-XX (2026-06-02).
  See the plugin's CLAUDE.md (https://github.com/theoju/engineering-docs-agent/blob/main/CLAUDE.md)
  for the durable plugin-side fix detail; the post-implementation note in this repo's spec
```

Substitute the real CCE key. Leave `PR #A` as a literal placeholder if the consumer PR isn't yet filed.

- [ ] **Step 3: Commit.**

```bash
git -C <consumer-main> add CLAUDE.md
git -C <consumer-main> commit -m "docs(pages): CLAUDE.md — shorten gotcha bullet, point at plugin CLAUDE.md — CCE-XX"
```

---

## Phase 6 — Consumer PR ship

### Task 15: Open the consumer PR (PR #A)

**Files:** None (git + gh only).

- [ ] **Step 1: Final pre-flight.**

Run:

```bash
cd <consumer-main>
npm test
git -C <consumer-main> log --oneline origin/main..HEAD
```

Expected: 689/689 tests pass; 4 commits ahead.

- [ ] **Step 2: Push the branch.**

```bash
git -C <consumer-main> push -u origin fix/CCE-XX-pages-cleanup
```

- [ ] **Step 3: Write the PR body to a file.**

Write `/tmp/pr-body-consumer-bootstrap.md`:

```markdown
## Summary

Consumer-side drive-by for CCE-XX. Mirrors the durable fix landing in `theoju/engineering-docs-agent` PR #B by dropping the misleading `enablement: true` line from this repo's `docs-agent-pages.yml` workflow (it was a no-op anyway — see the plugin PR for the full root cause). Flips the matching vitest assertion to be a regression guard against re-adding the line. Adds a one-line resolution footer to the existing POST-IMPLEMENTATION CORRECTION block in PR #121's spec. Shortens the CLAUDE.md gotcha bullet to point at the plugin's CLAUDE.md as the durable source.

**4 commits, ~13 LOC across 4 files.** Docs + workflow text only — no behavioral change.

### What changed

- `.github/workflows/docs-agent-pages.yml` — deleted misleading `with: enablement: true` block AND cleaned the matching wrong claim in the comment block at lines 3-6.
- `scripts/__tests__/docs-mkdocs-scaffold.test.mjs:76` — flipped `expect(body).toMatch(/enablement:\s*true/)` to `expect(body).not.toMatch(/enablement:\s*['"]?true['"]?/)`. Regression guard; broader regex matches quoted variants.
- `docs/superpowers/specs/2026-06-01-mkdocs-upgrade-design.md` — appended one-line "Resolved by" footer to the existing POST-IMPLEMENTATION CORRECTION block.
- `CLAUDE.md` — shortened the Pages enablement bullet to point at the plugin's CLAUDE.md as the durable source rather than repeating the explanation.

## Why now

The plugin PR (CCE-XX) lands the durable fix for every future host. This PR mirrors that fix to the one already-onboarded consumer host so its workflow stops carrying the misleading line and its tests guard against re-adding it.

## Test plan

- [x] `npm test` (689/689 passes locally, ~6s)
- [x] `mkdocs build --strict` exits 0 (unchanged from steady-state)
- [ ] **Post-merge:** next docs-touching push triggers `docs-agent-pages.yml`; deploy succeeds without `enablement: true` (Pages was bootstrapped via the manual recovery during CCE-81's incident on 2026-06-02; no behavior change today)

## Rollback

Single `git revert` of the squash-merge commit. Consumer keeps `enablement: true` as a no-op; plugin template stays fixed for future hosts.

## Linked work

- **Ticket:** [CCE-XX](https://designitright.atlassian.net/browse/CCE-XX)
- **Plugin PR (primary fix):** `theoju/engineering-docs-agent#<plugin-PR-N>` (forthcoming or merged)
- **Spec:** `theoju/engineering-docs-agent/docs/superpowers/specs/2026-06-02-pages-bootstrap-design.md`
- **Originating incident:** PR #121 / CCE-81

---

Generated with [Claude Code](https://claude.com/claude-code)
```

Substitute the real CCE key. Substitute the plugin PR number if Task 9 already opened it; otherwise leave `(forthcoming)`.

- [ ] **Step 4: Open the PR.**

```bash
gh pr create \
  --repo theoju/claude-code-self-assessment \
  --base main \
  --title "fix(pages): drop misleading enablement:true — CCE-XX" \
  --body-file /tmp/pr-body-consumer-bootstrap.md
```

Expected: returns the PR URL.

- [ ] **Step 5: Wait for consumer CI to pass.**

Run:

```bash
gh pr checks <PR#> --repo theoju/claude-code-self-assessment
```

Expected: `docs-build-check` passes (the path filter includes `.github/workflows/docs-agent-pages.yml` so the gate fires).

- [ ] **Step 6: Pause for user direction before squash-merging.**

After user approves:

```bash
gh pr merge <PR#> --repo theoju/claude-code-self-assessment --squash --subject "fix(pages): drop misleading enablement:true — CCE-XX (#<PR#>)"
gh pr view <PR#> --repo theoju/claude-code-self-assessment --json state,mergeCommit
```

Expected: MERGED + mergeCommit oid.

---

## Phase 7 — Close-the-loop

### Task 16: Comment on CCE-XX + transition to Done

**Files:** None (Jira only).

- [ ] **Step 1: Confirm both PRs are MERGED.**

```bash
gh pr view <plugin-PR#> --repo theoju/engineering-docs-agent --json state,mergeCommit,mergedAt
gh pr view <consumer-PR#> --repo theoju/claude-code-self-assessment --json state,mergeCommit,mergedAt
```

Expected: both `MERGED` with timestamps.

- [ ] **Step 2: Pause and ask user for per-action approval to post the close-the-loop Jira comment + transition.**

Per consumer CLAUDE.md: each Jira write is a per-action authorization. Do not auto-comment + auto-transition without explicit user direction.

Show the user the proposed comment:

```markdown
Shipped end-to-end.

**Status:** Done. Both PRs merged.

- **Plugin PR (primary fix):** theoju/engineering-docs-agent#<plugin-PR#>, mergeCommit `<sha>`. Templates + plugin's own dogfood workflow + new `scripts/enable_pages.py` (9 test cases) + SKILL.md step 6c + CLAUDE.md + CHANGELOG.
- **Consumer drive-by:** theoju/claude-code-self-assessment#<consumer-PR#>, mergeCommit `<sha>`. Workflow + test flip + spec annotation + CLAUDE.md pointer.
- **No runtime impact on existing hosts** — template + script + skill consumed only by NEW setup runs. Consumer's existing deploy continues working (Pages was bootstrapped during CCE-81 recovery on 2026-06-02).
- **Future hosts onboarded with `framework: mkdocs`** now get a clean workflow file + automatic Pages bootstrap via the setup skill. No manual `gh api` needed.

Spec: `docs/superpowers/specs/2026-06-02-pages-bootstrap-design.md` (plugin repo).
Closing as Done.
```

Substitute actual PR numbers, SHAs, and CCE key.

- [ ] **Step 3: After user approval, post the comment.**

```
mcp__plugin_atlassian_atlassian__addCommentToJiraIssue(
  cloudId="f375676f-949f-4187-8adf-c9e6bbdb8458",
  issueIdOrKey="CCE-XX",
  contentFormat="markdown",
  commentBody="<the comment above>"
)
```

- [ ] **Step 4: Get transitions for CCE-XX and pick the Done ID.**

```
mcp__plugin_atlassian_atlassian__getTransitionsForJiraIssue(
  cloudId="f375676f-949f-4187-8adf-c9e6bbdb8458",
  issueIdOrKey="CCE-XX"
)
```

Expected: find the transition with `name: "Done"`. Use its `id` (historically `41` for the CCE project, but verify in case the workflow changed).

- [ ] **Step 5: Pause again for per-action approval, then transition.**

```
mcp__plugin_atlassian_atlassian__transitionJiraIssue(
  cloudId="f375676f-949f-4187-8adf-c9e6bbdb8458",
  issueIdOrKey="CCE-XX",
  transition={"id": "<done-transition-id>"}
)
```

Expected: `{"success": true}`.

- [ ] **Step 6: Verify final state.**

```bash
gh pr view <plugin-PR#> --repo theoju/engineering-docs-agent --json state
gh pr view <consumer-PR#> --repo theoju/claude-code-self-assessment --json state
```

Plus visually confirm CCE-XX is in the Done column.

---

## Verification summary

After all 16 tasks complete, the spec's verification matrix should be satisfied:

| Gate                                                                   | Verification                                                   |
| ---------------------------------------------------------------------- | -------------------------------------------------------------- |
| B.pre-1: existing template test passes                                 | Task 4 Step 3 confirmed                                        |
| B.pre-2: 9 new CLI test cases pass                                     | Task 3 Step 3 confirmed (14 instances = 9 cases × parametrize) |
| B.pre-3: full plugin pytest passes                                     | Task 4 Step 4 confirmed                                        |
| B.pre-4: no `enablement: true` in template or dogfood workflow         | Tasks 4 + 5                                                    |
| B.pre-5: SKILL.md step 6a no longer carries wrong claim                | Task 6 Step 2                                                  |
| B.pre-6: SKILL.md step 6c references `enable_pages.py`                 | Task 6 Step 4                                                  |
| B.pre-7: CHANGELOG `[Unreleased]` has the Fixed entry                  | Task 8                                                         |
| B.pre-8: plugin CI passes                                              | Task 9 Step 5                                                  |
| A.pre-1: consumer `npm test` passes                                    | Task 12 Step 3                                                 |
| A.pre-2: no `enablement: true` in consumer workflow (YAML or comments) | Task 11                                                        |
| A.pre-3: consumer test asserts ABSENCE                                 | Task 12 Step 2                                                 |
| A.pre-4: `mkdocs build --strict` exits 0                               | unchanged from steady state                                    |
| A.pre-5: consumer `docs-build-check.yml` passes                        | Task 15 Step 5                                                 |

The 4 negative tests from the spec's "negative tests" table will all be in place after Tasks 1 + 2 + 11 + 12.

## Notes for the executor

- **TDD discipline:** Tasks 1 + 2 write tests BEFORE Tasks 3 + 4 + 5 implement them. Resist the temptation to combine — separate commits make the failure surface visible in git history.
- **Path placeholders:** every code block uses absolute paths. The consumer-repo placeholder `<consumer-main>` is the only real placeholder; substitute the actual checkout path once located.
- **`CCE-XX`:** replace with the resolved Jira key from Task 0a Step 3 in every commit message, PR title, PR body, file content. If unresolved at any step, halt and request the user file the ticket first.
- **If a step fails:** don't paper over with a workaround. Diagnose root cause. The plan's verification gates exist to catch real problems. Re-run the affected tests in isolation before moving on.
- **PR numbers (`PR #A` / `PR #B`):** are literal placeholders until both PRs are filed. Once filed, do a find-replace in any committed file that references them (specifically A3's spec annotation and A4's CLAUDE.md update may benefit from a final cleanup commit if PR numbers were unknown at the time of original commit).
- **Per-action Jira authorization** applies to Tasks 0a and 16 — each Jira write needs its own user approval, NOT a session-wide approval.
- **Worktree note:** the consumer's main checkout is NOT at `/Users/theo/Projects/claude-extensions/.claude/worktrees/engineering-docs-agent-integration` (that's a stale worktree). Find the real one before starting Task 10.

## Self-review checklist (executed by plan author)

- **Spec coverage:** Every spec deliverable (B0-B7, A1-A4) maps to at least one task. B0 → Task 1; B1 → Task 4; B2 → Task 3; B3 → Task 6; B4 → Task 7; B5 → Task 2; B6 → Task 5; B7 → Task 8; A1 → Task 11; A2 → Task 12; A3 → Task 13; A4 → Task 14. Plus ticket-filing (Task 0a), branching (Tasks 0b, 10), and PR shipping (Tasks 9, 15) and close-out (Task 16). All 12 spec deliverables covered.
- **Placeholder scan:** No "TBD" or "TODO" placeholders. `CCE-XX`, `PR #A`, `PR #B`, `<consumer-main>`, `<plugin-PR#>`, `<consumer-PR#>` are intentional substitution markers (documented in "Notes for the executor"), not placeholder gaps in the design.
- **Type consistency:** Function name `enable_pages(owner, repo)` is used consistently between Task 3 (Step 1 script body) and Task 2 (test cases that invoke it via subprocess). Script CLI flag names `--owner` and `--repo` are consistent across Task 3, Task 2, and the SKILL.md step 6c text in Task 6. The 409-detection regex `r"\(HTTP 409\)"` appears identically in Task 3 Step 1 (the script) and Task 2 Step 5 (the docstring of the false-positive test). Recovery template string `gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow` appears identically in Task 3 (`_RECOVERY_TEMPLATE`) and in test assertions in Tasks 2 and 11.

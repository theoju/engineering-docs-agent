"""CCE-90: prune_merged_branches helper tests.

Covers the in-repo periodic cleaner that prunes local branches whose
origin counterpart is gone (typical post-`gh pr merge --delete-branch`
state) and orphan `worktree-*` branches left behind by the Workflow
tool's worktree-isolation mode (Phase B / CCE-100 upstream).

All tests use a tmp git repo with a sham origin so the helper exercises
its real git plumbing without touching the host operator's refs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import prune_merged_branches as pmb  # noqa: E402


def _run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"setup cmd failed: {cmd!r}: {r.stderr}"
    return r.stdout.strip()


@pytest.fixture
def repo_with_origin(tmp_path):
    """Sham origin + local clone. Returns the local clone path.

    The origin is a bare repo on the filesystem with one main commit; the
    local clone tracks it. Tests build out branches on top and simulate
    the [gone] state by deleting the origin-side branch before invoking
    the helper.
    """
    origin = tmp_path / "origin.git"
    local = tmp_path / "local"
    _run(["git", "init", "--bare", "--initial-branch=main", str(origin)], cwd=tmp_path)

    _run(["git", "init", "--initial-branch=main", str(local)], cwd=tmp_path)
    _run(["git", "config", "user.email", "test@example.com"], cwd=local)
    _run(["git", "config", "user.name", "Test"], cwd=local)
    (local / "README.md").write_text("seed\n")
    _run(["git", "add", "README.md"], cwd=local)
    _run(["git", "commit", "-m", "seed"], cwd=local)
    _run(["git", "remote", "add", "origin", str(origin)], cwd=local)
    _run(["git", "push", "-u", "origin", "main"], cwd=local)
    return local


def _make_branch(repo, name, *, push=True, extra_commit=False):
    """Create a local branch + optionally push it to origin so [gone]
    detection has a tracking ref to nuke later."""
    _run(["git", "checkout", "-b", name], cwd=repo)
    if extra_commit:
        (repo / f"{name.replace('/', '_')}.md").write_text("change\n")
        _run(["git", "add", "."], cwd=repo)
        _run(["git", "commit", "-m", f"work on {name}"], cwd=repo)
    if push:
        _run(["git", "push", "-u", "origin", name], cwd=repo)
    _run(["git", "checkout", "main"], cwd=repo)


def _delete_origin_branch(repo, name):
    """Simulate `gh pr merge --delete-branch` — drop the origin-side ref
    only. The local copy is left in place; `git fetch --prune` will then
    mark it [gone]."""
    _run(["git", "push", "origin", "--delete", name], cwd=repo)


# ---------- discovery ----------


def test_find_pruneable_returns_empty_on_clean_repo(repo_with_origin):
    branches = pmb.find_pruneable_branches(repo_with_origin)
    assert branches == []


def test_find_pruneable_skips_branches_with_live_origin(repo_with_origin):
    _make_branch(repo_with_origin, "feat/live-1", extra_commit=True)
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    branches = pmb.find_pruneable_branches(repo_with_origin)
    assert branches == [], "live origin branch must not be pruneable"


def test_find_pruneable_flags_branches_whose_origin_is_gone(repo_with_origin):
    _make_branch(repo_with_origin, "feat/landed-1", extra_commit=True)
    _delete_origin_branch(repo_with_origin, "feat/landed-1")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    branches = pmb.find_pruneable_branches(repo_with_origin)
    names = [b.name for b in branches]
    assert "feat/landed-1" in names
    target = next(b for b in branches if b.name == "feat/landed-1")
    assert target.reason == "gone"


def test_find_pruneable_never_includes_main(repo_with_origin):
    _make_branch(repo_with_origin, "feat/landed-2", extra_commit=True)
    _delete_origin_branch(repo_with_origin, "feat/landed-2")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    branches = pmb.find_pruneable_branches(repo_with_origin)
    names = [b.name for b in branches]
    assert "main" not in names, "main must be hard-excluded from prune set"


def test_find_pruneable_never_includes_current_branch(repo_with_origin):
    _make_branch(repo_with_origin, "feat/landed-3", extra_commit=True)
    _delete_origin_branch(repo_with_origin, "feat/landed-3")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    # Sit ON the [gone] branch.
    _run(["git", "checkout", "feat/landed-3"], cwd=repo_with_origin)
    branches = pmb.find_pruneable_branches(repo_with_origin)
    names = [b.name for b in branches]
    assert "feat/landed-3" not in names, (
        "current branch must be excluded — deleting it would orphan the working tree"
    )


def test_find_pruneable_excludes_branch_checked_out_in_linked_worktree(
    repo_with_origin, tmp_path
):
    """CCE-116: a [gone] branch checked out in ANOTHER worktree cannot be
    deleted (git branch -d/-D refuse), so it must be excluded from the prune
    set — not classified `gone` and then misreported as skipped_unmerged."""
    _make_branch(repo_with_origin, "feat/wt-live", extra_commit=True)
    # Check the branch out in a linked worktree (main worktree stays on main).
    wt_path = tmp_path / "linked-wt"
    _run(["git", "worktree", "add", str(wt_path), "feat/wt-live"], cwd=repo_with_origin)
    _delete_origin_branch(repo_with_origin, "feat/wt-live")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)

    branches = pmb.find_pruneable_branches(repo_with_origin)
    names = [b.name for b in branches]
    assert "feat/wt-live" not in names, (
        "a branch checked out in a linked worktree must be excluded — "
        "git refuses to delete it, so classifying it pruneable misreports the outcome"
    )


def test_find_pruneable_still_flags_gone_branch_not_in_any_worktree(repo_with_origin):
    """Regression guard for CCE-116: the worktree exclusion must not suppress a
    normal [gone] branch that is not checked out anywhere."""
    _make_branch(repo_with_origin, "feat/wt-none", extra_commit=True)
    _delete_origin_branch(repo_with_origin, "feat/wt-none")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    branches = pmb.find_pruneable_branches(repo_with_origin)
    assert "feat/wt-none" in [b.name for b in branches]


def test_find_pruneable_flags_worktree_orphans_without_origin(repo_with_origin):
    """CCE-100 floor: detect the `worktree-*` orphan refs the Workflow
    tool's isolation mode leaves behind. They have no origin counterpart;
    presence of the prefix alone is the signal."""
    # No push — local-only branch with the worktree-* naming.
    _make_branch(repo_with_origin, "worktree-wf_abc123-1", push=False)
    branches = pmb.find_pruneable_branches(repo_with_origin)
    names = [(b.name, b.reason) for b in branches]
    assert ("worktree-wf_abc123-1", "worktree_orphan") in names


def test_find_pruneable_respects_protect_list(repo_with_origin):
    _make_branch(repo_with_origin, "release/v1.0.0", extra_commit=True)
    _delete_origin_branch(repo_with_origin, "release/v1.0.0")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    branches = pmb.find_pruneable_branches(
        repo_with_origin, protect=("main", "release/v1.0.0")
    )
    names = [b.name for b in branches]
    assert "release/v1.0.0" not in names


# ---------- apply ----------


def test_prune_apply_deletes_safe_merged_branch(repo_with_origin):
    """A [gone] branch with no unmerged commits → -d succeeds → branch removed."""
    _make_branch(repo_with_origin, "feat/landed-4", extra_commit=False)
    _delete_origin_branch(repo_with_origin, "feat/landed-4")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    branches = pmb.find_pruneable_branches(repo_with_origin)
    target = next(b for b in branches if b.name == "feat/landed-4")
    result = pmb.prune_branch(repo_with_origin, target)
    assert result.ok is True
    assert result.action == "deleted"
    after = _run(["git", "branch", "--format=%(refname:short)"], cwd=repo_with_origin)
    assert "feat/landed-4" not in after.split()


def test_prune_apply_safe_skips_branch_with_unmerged_commits(repo_with_origin):
    """A [gone] branch whose tip is NOT in main's history → -d refuses →
    helper must safe-skip with action='skipped_unmerged', NOT escalate to
    -D unless the caller passes force=True explicitly.
    """
    _make_branch(repo_with_origin, "feat/landed-5", extra_commit=True)
    _delete_origin_branch(repo_with_origin, "feat/landed-5")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    branches = pmb.find_pruneable_branches(repo_with_origin)
    target = next(b for b in branches if b.name == "feat/landed-5")
    result = pmb.prune_branch(repo_with_origin, target, force=False)
    assert result.ok is True
    assert result.action == "skipped_unmerged"
    after = _run(["git", "branch", "--format=%(refname:short)"], cwd=repo_with_origin)
    assert "feat/landed-5" in after.split(), "must NOT delete unmerged branch"


def test_prune_apply_force_deletes_unmerged_when_requested(repo_with_origin):
    _make_branch(repo_with_origin, "feat/landed-6", extra_commit=True)
    _delete_origin_branch(repo_with_origin, "feat/landed-6")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    branches = pmb.find_pruneable_branches(repo_with_origin)
    target = next(b for b in branches if b.name == "feat/landed-6")
    result = pmb.prune_branch(repo_with_origin, target, force=True)
    assert result.ok is True
    assert result.action == "force_deleted"
    after = _run(["git", "branch", "--format=%(refname:short)"], cwd=repo_with_origin)
    assert "feat/landed-6" not in after.split()


def test_prune_apply_worktree_orphan_uses_force(repo_with_origin):
    """Worktree orphans have no origin; their commits never landed on main.
    -d would refuse. The helper auto-escalates for the worktree_orphan
    bucket since the orphan is by definition stranded work the operator
    never planned to land.
    """
    _make_branch(
        repo_with_origin, "worktree-wf_xyz789-2", push=False, extra_commit=True
    )
    branches = pmb.find_pruneable_branches(repo_with_origin)
    target = next(b for b in branches if b.name == "worktree-wf_xyz789-2")
    result = pmb.prune_branch(repo_with_origin, target)  # no explicit force
    assert result.ok is True
    assert result.action == "force_deleted"
    after = _run(["git", "branch", "--format=%(refname:short)"], cwd=repo_with_origin)
    assert "worktree-wf_xyz789-2" not in after.split()


# ---------- CLI dry-run / apply ----------


def test_cli_dry_run_lists_without_deleting(repo_with_origin, capsys):
    _make_branch(repo_with_origin, "feat/cli-dry-1", extra_commit=False)
    _delete_origin_branch(repo_with_origin, "feat/cli-dry-1")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    rc = pmb.main(["--repo-root", str(repo_with_origin)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "feat/cli-dry-1" in captured.out
    assert "dry-run" in captured.out.lower()
    after = _run(["git", "branch", "--format=%(refname:short)"], cwd=repo_with_origin)
    assert "feat/cli-dry-1" in after.split(), "dry-run must NOT delete"


def test_cli_apply_deletes_and_reports(repo_with_origin, capsys):
    _make_branch(repo_with_origin, "feat/cli-apply-1", extra_commit=False)
    _delete_origin_branch(repo_with_origin, "feat/cli-apply-1")
    _run(["git", "fetch", "--prune"], cwd=repo_with_origin)
    rc = pmb.main(["--repo-root", str(repo_with_origin), "--apply"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "feat/cli-apply-1" in captured.out
    assert "deleted" in captured.out.lower()
    after = _run(["git", "branch", "--format=%(refname:short)"], cwd=repo_with_origin)
    assert "feat/cli-apply-1" not in after.split()


def test_cli_apply_exit_0_when_nothing_to_prune(repo_with_origin, capsys):
    rc = pmb.main(["--repo-root", str(repo_with_origin), "--apply"])
    captured = capsys.readouterr()
    assert rc == 0
    assert (
        "nothing to prune" in captured.out.lower() or "0 branch" in captured.out.lower()
    )

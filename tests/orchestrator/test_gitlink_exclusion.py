"""CCE-70 + CCE-75: orchestrator staging helper must survive both layouts.

CCE-70 case: host does NOT gitignore `.docs-agent-plugin`. Without
explicit handling, `git add .` would register the nested actions/checkout
as a submodule entry (mode 160000) in the host's docs-agent PR.

CCE-75 case: host DOES gitignore `.docs-agent-plugin`. The original
fix for CCE-70 used a negative pathspec (`:!.docs-agent-plugin`); on
hosts where the same path is in `.gitignore`, naming the path in the
pathspec promotes it to "explicitly mentioned" and triggers git's
gitignore-aware safety check (`paths are ignored by one of your
.gitignore files`), failing the whole stage. The fix must work on
both layouts without distinguishing between them at the call site.
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def _init_git_repo(path: Path) -> None:
    """Initialize a real git repo at `path` with author config and an
    initial empty commit.

    Real host repos always have a HEAD commit (they're clones of an
    upstream remote). Skipping the initial commit creates a "no HEAD"
    state that doesn't exist in production and breaks index operations
    like `git restore --staged` that resolve relative to HEAD.
    """
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.local"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "--allow-empty", "-m", "init"],
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

    staged = (
        subprocess.run(
            ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )

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

    staged = set(
        subprocess.run(
            ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )

    assert ".engineering-docs-agent/state.json" in staged
    assert "docs/whats-new.md" in staged
    assert "docs/page.md" in staged


def test_stage_docs_run_changes_with_plugin_in_host_gitignore(tmp_path: Path) -> None:
    """CCE-75: hosts may add `.docs-agent-plugin` to their `.gitignore`.

    Mirrors the ADIS layout that caused the silent exit-1 in run
    26773177931. With `.docs-agent-plugin` gitignored, the previous
    negative-pathspec approach errored with `paths are ignored by one
    of your .gitignore files`. The staging helper must succeed and
    stage the orchestrator's legitimate outputs (state.json, docs
    files) while the plugin checkout stays out of the index.
    """
    _init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".docs-agent-plugin/\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "host gitignore"],
        check=True,
    )

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text("# authored page\n")
    _create_nested_plugin_checkout(tmp_path)

    rc, stderr = orun._stage_docs_run_changes(tmp_path)
    assert rc == 0, (
        f"staging must succeed even when plugin path is gitignored; "
        f"rc={rc}, stderr={stderr!r}"
    )

    staged = (
        subprocess.run(
            ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )

    assert "docs/page.md" in staged, f"authored docs page must be staged; got {staged}"
    plugin_entries = [p for p in staged if p.startswith(".docs-agent-plugin")]
    assert not plugin_entries, (
        f"no .docs-agent-plugin/* entries should be staged; got {plugin_entries}"
    )


def test_stage_docs_run_changes_preserves_pre_tracked_plugin_content(
    tmp_path: Path,
) -> None:
    """Adversarial scenario: host has unrelated content tracked under
    `.docs-agent-plugin/` from before the plugin was adopted (or
    committed by mistake).

    The previous negative-pathspec implementation left such tracked
    content alone. The new implementation MUST do the same — `git
    restore --staged` reverts the index to match HEAD, so files
    already tracked at HEAD stay tracked and are not staged for
    deletion.
    """
    _init_git_repo(tmp_path)
    plugin = tmp_path / ".docs-agent-plugin"
    plugin.mkdir()
    (plugin / "legacy.txt").write_text("pre-existing tracked content\n")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", ".docs-agent-plugin"], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "commit",
            "-q",
            "-m",
            "pre-existing plugin content",
        ],
        check=True,
    )

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text("# authored page\n")

    rc, stderr = orun._stage_docs_run_changes(tmp_path)
    assert rc == 0, f"staging failed: rc={rc}, stderr={stderr!r}"

    tracked_at_head = (
        subprocess.run(
            ["git", "-C", str(tmp_path), "ls-tree", "-r", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    assert ".docs-agent-plugin/legacy.txt" in tracked_at_head, (
        f"pre-existing tracked content must remain in HEAD; got {tracked_at_head}"
    )

    staged_deletions = (
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "diff",
                "--cached",
                "--diff-filter=D",
                "--name-only",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    assert ".docs-agent-plugin/legacy.txt" not in staged_deletions, (
        f"pre-existing tracked content must NOT be staged for deletion; got staged deletions {staged_deletions}"
    )


def test_stage_docs_run_changes_drops_midrun_modifications_to_tracked_plugin_content(
    tmp_path: Path,
) -> None:
    """CCE-75 polish: mid-run modifications to tracked content under
    `.docs-agent-plugin/` are dropped from the docs commit.

    The helper's `restore --staged` step is gated on whether ANY
    `.docs-agent-plugin/*` entry made it into the index. When a host
    has pre-tracked content there AND it's been modified during the
    run (orchestrator bug, careless subagent write, whatever), the
    modification gets staged by `git add -A .`, the diff probe finds
    it, and the restore step reverts the index entry to HEAD. Net
    effect: the modification is silently not committed. Docs runs
    should never mutate the plugin tree on the runner, so this is
    correct — but pinning it prevents future refactors from silently
    regressing it.
    """
    _init_git_repo(tmp_path)
    plugin = tmp_path / ".docs-agent-plugin"
    plugin.mkdir()
    (plugin / "tracked.txt").write_text("baseline content\n")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", ".docs-agent-plugin"], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "commit",
            "-q",
            "-m",
            "pre-tracked plugin content",
        ],
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


def test_stage_docs_run_changes_bare_pathspec_does_not_overselect_siblings(
    tmp_path: Path,
) -> None:
    """CCE-75 polish: bare pathspec `-- .docs-agent-plugin` matches the
    gitlink entry itself AND under-directory entries — but NOT siblings
    like `.docs-agent-plugin-notes.md` that share a common string prefix.

    Git pathspec rule: a literal pathspec matches if the path equals
    the spec OR begins with `<spec>/`. So `.docs-agent-plugin` matches
      - `.docs-agent-plugin` (the gitlink — exact match)
      - `.docs-agent-plugin/foo` (under-directory — prefix-followed-by-slash)
    but NOT `.docs-agent-plugin-notes.md` (no trailing slash before `-`).

    Why this test exists: a validator panel suggested "tightening" the
    diff probe to `:(glob).docs-agent-plugin/**` on the assumption that
    the bare form over-selects siblings. Empirical verification proved
    otherwise. A `:(glob)/**` rewrite would actively REGRESS the helper
    because production gitlink entries sit at `.docs-agent-plugin` with
    NO trailing slash and would not match `<path>/**`. This test pins
    the correct behavior so a future "tightening" attempt is caught at
    test time, not in production:

    (a) Direct pathspec assertion against an injected gitlink (via
        `git update-index --cacheinfo`, which mirrors production's
        actions/checkout layout) — proves bare pathspec matches the
        gitlink, which a `:(glob)/**` rewrite would NOT.
    (b) Direct pathspec assertion against a sibling — proves bare form
        does NOT prefix-match across path boundaries.
    """
    _init_git_repo(tmp_path)

    (tmp_path / ".docs-agent-plugin-notes.md").write_text(
        "# notes about the docs-agent plugin\n"
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", ".docs-agent-plugin-notes.md"],
        capture_output=True,
        text=True,
        check=True,
    )

    # Inject a gitlink at `.docs-agent-plugin`. cacheinfo format:
    # `<mode>,<sha>,<path>` where 160000 is the gitlink mode. Git
    # validates the SHA against its object database (all-zeros is
    # rejected as a null entry), so reuse the repo's own initial
    # commit SHA — any real object SHA is accepted for a gitlink and
    # the pathspec layer doesn't follow the target.
    head_sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{head_sha},.docs-agent-plugin",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    all_staged = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert ".docs-agent-plugin" in all_staged, (
        f"setup error: gitlink injection failed; got staged: {all_staged}"
    )
    assert ".docs-agent-plugin-notes.md" in all_staged, (
        f"setup error: sibling not staged; got staged: {all_staged}"
    )

    bare_match = subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "diff",
            "--cached",
            "--name-only",
            "--",
            ".docs-agent-plugin",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    assert ".docs-agent-plugin" in bare_match, (
        f"bare pathspec MUST match the gitlink entry `.docs-agent-plugin`; "
        f"got: {bare_match}. A `:(glob).docs-agent-plugin/**` rewrite would "
        f"fail this — the gitlink has no trailing slash so `/**` would not "
        f"match it, breaking CCE-70 coverage in production."
    )
    assert ".docs-agent-plugin-notes.md" not in bare_match, (
        f"bare pathspec MUST NOT prefix-match `.docs-agent-plugin-notes.md`; "
        f"git pathspec requires exact-match or prefix-followed-by-slash. "
        f"got: {bare_match}"
    )

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

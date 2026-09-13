"""CCE-170: the current_run.json sibling must be gitignored on HOSTS too.

`state_io.save_current_run` documented the sibling as "gitignored (see
.gitignore) and not part of the merge-as-promotion path". That is true in the
agent repo, whose own .gitignore lists it. Hosts do not inherit that file, and
`_stage_docs_run_changes` stages with `git add -A .`, so on a host every run
committed ephemeral per-run state into the docs PR.

Measured on host `theoju/claude-code-self-assessment` (checked out locally as
`claude-extensions`): `git check-ignore` exits 1, the path is tracked, and 26
commits have touched it — three more than when the ticket was filed, so the
churn is ongoing rather than historical.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

ENTRY = ".engineering-docs-agent/current_run.json"

SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [{"key": "home", "path": "index.md", "title": "Home"}],
}


def _git(repo: Path, *args: str):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )


def _host(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    return tmp_path


# ---------- the invariant this repo actually holds ----------


def test_the_agent_repo_gitignores_its_own_run_state():
    """The half of the docstring that IS true, pinned so it stays true."""
    lines = (_REPO_ROOT / ".gitignore").read_text().splitlines()
    assert ENTRY in [ln.strip() for ln in lines]


# ---------- and what onboarding must now do for a host ----------


def test_onboarding_adds_the_entry_to_a_host_gitignore(tmp_path: Path):
    host = _host(tmp_path)
    (host / ".gitignore").write_text("node_modules/\n")
    status = site_structure.ensure_run_state_gitignored(host)
    assert status == "added"
    assert _git(host, "check-ignore", "-q", "--no-index", "--", ENTRY).returncode == 0
    assert "node_modules/" in (host / ".gitignore").read_text()


def test_onboarding_creates_a_gitignore_when_the_host_has_none(tmp_path: Path):
    host = _host(tmp_path)
    status = site_structure.ensure_run_state_gitignored(host)
    assert status == "created"
    assert _git(host, "check-ignore", "-q", "--no-index", "--", ENTRY).returncode == 0


def test_onboarding_is_idempotent(tmp_path: Path):
    host = _host(tmp_path)
    site_structure.ensure_run_state_gitignored(host)
    first = (host / ".gitignore").read_text()
    assert site_structure.ensure_run_state_gitignored(host) == "already-ignored"
    assert (host / ".gitignore").read_text() == first


def test_a_broader_host_pattern_is_respected_rather_than_duplicated(tmp_path: Path):
    """Ask git, not a string compare: a host that already ignores the whole
    directory needs no second line, and adding one implies it was missing."""
    host = _host(tmp_path)
    (host / ".gitignore").write_text(".engineering-docs-agent/\n")
    assert site_structure.ensure_run_state_gitignored(host) == "already-ignored"
    assert (host / ".gitignore").read_text() == ".engineering-docs-agent/\n"


def test_an_already_tracked_path_is_reported_as_inert(tmp_path: Path):
    """THE CORRECTION TO THE TICKET. Option 2 claims it "removes both the churn
    and the latent failure". It does so for hosts onboarded AFTER this change.
    On a host where the file is already tracked -- the measured state of
    claude-code-self-assessment, 26 commits deep -- .gitignore has no effect at
    all, and `git add -A .` keeps staging it until someone runs
    `git rm --cached`. Say so instead of reporting success."""
    host = _host(tmp_path)
    run_state = host / ".engineering-docs-agent"
    run_state.mkdir()
    (run_state / "current_run.json").write_text("{}\n")
    _git(host, "add", "-A")
    _git(host, "commit", "-qm", "host already committed run state")

    status = site_structure.ensure_run_state_gitignored(host)
    assert status == "added-but-inert-path-is-tracked"
    assert _git(host, "ls-files", "--error-unmatch", ENTRY).returncode == 0


def test_a_non_git_host_degrades_without_raising(tmp_path: Path):
    """Generic-first: scaffolding a directory that is not a git repo must not
    error. git check-ignore exits 128 there, which is not "already ignored"."""
    status = site_structure.ensure_run_state_gitignored(tmp_path)
    assert status in {"created", "added"}
    assert ENTRY in (tmp_path / ".gitignore").read_text()


def test_apply_scaffold_reports_the_gitignore_outcome(tmp_path: Path):
    """Wired into onboarding, and visible in the JSON the setup skill prints."""
    host = _host(tmp_path)
    result = site_structure.apply_scaffold(
        host, SITE, site_name="Demo", python_detected=False
    )
    assert result["run_state_gitignore"] in {"created", "added", "already-ignored"}
    assert _git(host, "check-ignore", "-q", "--no-index", "--", ENTRY).returncode == 0

"""Pins `detect_repo`'s three sources, in precedence order.

This exists because of the fix beside it. `conftest._pin_repo_slug` is
autouse across this whole directory, so from here on every orchestrator test
sees `GITHUB_REPOSITORY=unknown/unknown` — which means none of them can ever
again notice if `detect_repo` stopped reading the environment and started
returning the sentinel unconditionally. Every assertion keyed on a computed
pr_id would still pass.

That is the same shape as the bug the fixture fixes, one layer down: a guard
that cannot see its own subject. So the subject gets its own test, and these
override the fixture explicitly rather than inheriting it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from orchestrator_runner import detect_repo  # noqa: E402


def _repo_with_remote(path: Path, url: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", url], check=True)
    return path


def test_the_environment_wins_over_the_remote(tmp_path, monkeypatch):
    """CI's $GITHUB_REPOSITORY is authoritative even when a remote disagrees.

    The overridden value is deliberately NOT the sentinel: if this asserted
    `unknown/unknown` it would pass whether or not the env branch ran at all.
    """
    repo = _repo_with_remote(tmp_path / "host", "https://github.com/other/repo.git")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widgets")
    assert detect_repo(repo) == {"owner": "acme", "name": "widgets"}


def test_the_origin_remote_is_used_when_the_environment_is_unset(tmp_path, monkeypatch):
    repo = _repo_with_remote(tmp_path / "host", "https://github.com/acme/widgets.git")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert detect_repo(repo) == {"owner": "acme", "name": "widgets"}


def test_an_ssh_remote_parses_the_same_way(tmp_path, monkeypatch):
    repo = _repo_with_remote(tmp_path / "host", "git@github.com:acme/widgets.git")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert detect_repo(repo) == {"owner": "acme", "name": "widgets"}


def test_a_repo_with_no_remote_falls_back_to_the_sentinel(tmp_path, monkeypatch):
    """The state every `init_host` scaffold is in, and the reason the shared
    fixtures hardcode `unknown/unknown#1`."""
    repo = tmp_path / "host"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert detect_repo(repo) == {"owner": "unknown", "name": "unknown"}


def test_a_malformed_environment_value_does_not_win(tmp_path, monkeypatch):
    """`detect_repo` only accepts the env var when it contains a slash, so a
    truncated or placeholder value must fall through to the remote rather than
    silently producing a half-formed slug."""
    repo = _repo_with_remote(tmp_path / "host", "https://github.com/acme/widgets.git")
    monkeypatch.setenv("GITHUB_REPOSITORY", "no-slash-here")
    assert detect_repo(repo) == {"owner": "acme", "name": "widgets"}

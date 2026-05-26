from __future__ import annotations

import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import archive_indexes  # noqa: E402


def test_explicit_override_wins_and_normalizes_trailing_slash(tmp_path):
    base = archive_indexes.resolve_repo_url_base(
        tmp_path, {}, override="https://x/blob/main"
    )
    assert base == "https://x/blob/main/"


def test_section_repo_url_base_used(tmp_path):
    section = {"repo_url_base": "https://y/blob/dev/"}
    assert (
        archive_indexes.resolve_repo_url_base(tmp_path, section)
        == "https://y/blob/dev/"
    )


def test_derived_github_url(monkeypatch, tmp_path):
    monkeypatch.setattr(
        archive_indexes, "detect_repo", lambda r: {"owner": "o", "name": "n"}
    )
    monkeypatch.setattr(
        archive_indexes.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout="feature\n", returncode=0),
    )
    base = archive_indexes.resolve_repo_url_base(tmp_path, {})
    assert base == "https://github.com/o/n/blob/feature/"


def test_unknown_repo_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(
        archive_indexes,
        "detect_repo",
        lambda r: {"owner": "unknown", "name": "unknown"},
    )
    assert archive_indexes.resolve_repo_url_base(tmp_path, {}) is None


def test_detached_head_defaults_to_main(monkeypatch, tmp_path):
    monkeypatch.setattr(
        archive_indexes, "detect_repo", lambda r: {"owner": "o", "name": "n"}
    )
    monkeypatch.setattr(
        archive_indexes.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout="HEAD\n", returncode=0),
    )
    assert archive_indexes.resolve_repo_url_base(tmp_path, {}) == (
        "https://github.com/o/n/blob/main/"
    )


def test_git_failure_defaults_to_main(monkeypatch, tmp_path):
    # git unavailable / not a repo (returncode != 0) -> ref falls back to main
    monkeypatch.setattr(
        archive_indexes, "detect_repo", lambda r: {"owner": "o", "name": "n"}
    )
    monkeypatch.setattr(
        archive_indexes.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout="", returncode=1),
    )
    assert archive_indexes.resolve_repo_url_base(tmp_path, {}) == (
        "https://github.com/o/n/blob/main/"
    )

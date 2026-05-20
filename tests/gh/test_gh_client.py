from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

FIXTURES = Path(__file__).parent.parent / "gh_fixtures"


def _fake_run(stdout="", stderr="", returncode=0, raise_exc=None):
    def _r(*args, **kwargs):
        if raise_exc:
            raise raise_exc
        return subprocess.CompletedProcess(
            args[0], returncode, stdout=stdout, stderr=stderr
        )

    return _r


def test_pr_view_files_parses_canned(monkeypatch, tmp_path):
    from gh_client import GhClient

    canned = (FIXTURES / "pr_view_files_ok.json").read_text()
    monkeypatch.setattr("gh_client.subprocess.run", _fake_run(stdout=canned))

    gh = GhClient(tmp_path)
    r = gh.pr_view_files(42)
    assert r.ok
    assert r.value == ["docs/site-src/foo.md", "docs/site-src/bar.md"]


def test_pr_view_files_gh_not_installed(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run", _fake_run(raise_exc=FileNotFoundError())
    )

    gh = GhClient(tmp_path)
    r = gh.pr_view_files(42)
    assert not r.ok
    assert r.error == "gh_not_installed"


def test_pr_view_files_bad_json(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr("gh_client.subprocess.run", _fake_run(stdout="not json"))
    gh = GhClient(tmp_path)
    r = gh.pr_view_files(42)
    assert not r.ok
    assert r.error.startswith("gh_bad_json")


def test_pr_list_for_branch_empty(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(stdout=(FIXTURES / "pr_list_empty.json").read_text()),
    )
    gh = GhClient(tmp_path)
    r = gh.pr_list_for_branch("docs-agent/2026-05-20T07")
    assert r.ok
    assert r.value is None


def test_pr_list_for_branch_existing(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(stdout=(FIXTURES / "pr_list_existing.json").read_text()),
    )
    gh = GhClient(tmp_path)
    r = gh.pr_list_for_branch("docs-agent/2026-05-20T07")
    assert r.ok
    assert r.value == 142


def test_pr_create_url_int_strategy(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(stdout="https://github.com/owner/repo/pull/99\n"),
    )
    gh = GhClient(tmp_path)
    r = gh.pr_create("docs-agent/x", "title", "body")
    assert r.ok
    assert r.value == 99


def test_pr_create_regex_strategy(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(
            stdout="View pull request: https://github.com/owner/repo/pull/77 (created)\n"
        ),
    )
    gh = GhClient(tmp_path)
    r = gh.pr_create("docs-agent/x", "title", "body")
    assert r.ok
    assert r.value == 77


def test_pr_create_falls_back_to_pr_list(monkeypatch, tmp_path):
    from gh_client import GhClient

    calls = {"n": 0}

    def fake_run(cmd, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="weird gh output", stderr=""
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='[{"number": 55}]', stderr="")

    monkeypatch.setattr("gh_client.subprocess.run", fake_run)
    gh = GhClient(tmp_path)
    r = gh.pr_create("docs-agent/x", "title", "body")
    assert r.ok
    assert r.value == 55


def test_pr_create_gh_failure(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(returncode=1, stderr="auth error"),
    )
    gh = GhClient(tmp_path)
    r = gh.pr_create("docs-agent/x", "title", "body")
    assert not r.ok
    assert "gh_pr_create_failed" in r.error

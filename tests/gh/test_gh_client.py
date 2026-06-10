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


def test_fake_gh_client_records_calls():
    from gh_client import FakeGhClient, GhResult

    fake = FakeGhClient(
        pr_view_files=GhResult(ok=True, value=["a.md", "b.md"]),
    )
    r = fake.pr_view_files(42)
    assert r.value == ["a.md", "b.md"]
    assert fake.calls == [("pr_view_files", (42,))]


def test_fake_gh_client_default_responses():
    from gh_client import FakeGhClient

    fake = FakeGhClient()
    assert fake.pr_view_files(1).value == []
    assert fake.pr_list_for_branch("x").value is None
    assert fake.pr_create("x", "t", "b").value == 1


def test_pr_checks_all_green(monkeypatch, tmp_path):
    from gh_client import GhClient

    stdout = json.dumps([{"name": "pytest", "state": "SUCCESS", "bucket": "pass"}])
    monkeypatch.setattr("gh_client.subprocess.run", _fake_run(stdout=stdout))
    r = GhClient(tmp_path).pr_checks(7)
    assert r.ok
    assert r.value[0]["name"] == "pytest"


def test_pr_checks_pending_exit_8_is_data_not_error(monkeypatch, tmp_path):
    """gh pr checks exits 8 while checks are pending; the JSON on stdout
    is still the payload. Treat it as data."""
    from gh_client import GhClient

    stdout = json.dumps([{"name": "pytest", "state": "PENDING", "bucket": "pending"}])
    monkeypatch.setattr(
        "gh_client.subprocess.run", _fake_run(stdout=stdout, returncode=8)
    )
    r = GhClient(tmp_path).pr_checks(7)
    assert r.ok
    assert r.value[0]["bucket"] == "pending"


def test_pr_checks_no_checks_reported_is_empty_list(monkeypatch, tmp_path):
    """No-App-token hosts: docs-agent PRs trigger no CI at all. gh exits
    non-zero with 'no checks reported' — that is the zero-checks case,
    not an error."""
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(stderr="no checks reported on the 'x' branch", returncode=1),
    )
    r = GhClient(tmp_path).pr_checks(7)
    assert r.ok
    assert r.value == []


def test_pr_checks_gh_not_installed(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run", _fake_run(raise_exc=FileNotFoundError())
    )
    r = GhClient(tmp_path).pr_checks(7)
    assert not r.ok
    assert r.error == "gh_not_installed"


def test_pr_checks_garbage_nonzero_is_error(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(stdout="boom", stderr="server error", returncode=1),
    )
    r = GhClient(tmp_path).pr_checks(7)
    assert not r.ok
    assert r.error.startswith("gh_pr_checks_failed")


def test_pr_checks_failing_exit_1_with_json_is_data(monkeypatch, tmp_path):
    """A genuine check failure returns exit 1 WITH a JSON payload on
    stdout. JSON acceptance must not be gated on returncode — the caller
    classifies red/green from state/bucket (CCE-83)."""
    from gh_client import GhClient

    stdout = json.dumps([{"name": "pytest", "state": "FAILURE", "bucket": "fail"}])
    monkeypatch.setattr(
        "gh_client.subprocess.run", _fake_run(stdout=stdout, returncode=1)
    )
    r = GhClient(tmp_path).pr_checks(7)
    assert r.ok
    assert r.value[0]["bucket"] == "fail"


def test_pr_merge_success_builds_squash_delete_argv(monkeypatch, tmp_path):
    from gh_client import GhClient

    seen = {}

    def _capture(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("gh_client.subprocess.run", _capture)
    r = GhClient(tmp_path).pr_merge(7)
    assert r.ok and r.value == 7
    assert seen["cmd"] == [
        "gh",
        "pr",
        "merge",
        "7",
        "--squash",
        "--delete-branch",
    ]


def test_pr_merge_failure_surfaces_stderr(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(stderr="branch protection", returncode=1),
    )
    r = GhClient(tmp_path).pr_merge(7)
    assert not r.ok
    assert r.error.startswith("gh_pr_merge_failed")
    assert "branch protection" in r.error


def test_workflow_run_dispatches_on_default_branch(monkeypatch, tmp_path):
    """No --ref: gh defaults to the repo's default branch, so the dispatch
    works on hosts whose default is master/trunk (generic-first)."""
    from gh_client import GhClient

    seen = {}

    def _capture(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("gh_client.subprocess.run", _capture)
    r = GhClient(tmp_path).workflow_run("docs-agent-pages.yml")
    assert r.ok
    assert seen["cmd"] == [
        "gh",
        "workflow",
        "run",
        "docs-agent-pages.yml",
    ]


def test_workflow_run_failure(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run", _fake_run(stderr="404", returncode=1)
    )
    r = GhClient(tmp_path).workflow_run("docs-agent-pages.yml")
    assert not r.ok
    assert r.error.startswith("gh_workflow_run_failed")


def test_fake_gh_client_pr_checks_sequence_pops_then_repeats_last():
    """Poll-loop tests feed a pending→green sequence; the last element
    repeats so a loop that polls extra times doesn't IndexError."""
    from gh_client import FakeGhClient, GhResult

    pending = GhResult(
        ok=True, value=[{"name": "ci", "state": "PENDING", "bucket": "pending"}]
    )
    green = GhResult(
        ok=True, value=[{"name": "ci", "state": "SUCCESS", "bucket": "pass"}]
    )
    fake = FakeGhClient(pr_checks=[pending, green])
    assert fake.pr_checks(1).value[0]["bucket"] == "pending"
    assert fake.pr_checks(1).value[0]["bucket"] == "pass"
    assert fake.pr_checks(1).value[0]["bucket"] == "pass"  # last repeats
    assert fake.calls.count(("pr_checks", (1,))) == 3

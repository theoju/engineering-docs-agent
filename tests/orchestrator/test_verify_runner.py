from __future__ import annotations
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

VERIFY_RUNNER = Path(__file__).parent.parent.parent / "scripts" / "verify_runner.py"
FAKES_VERIFY_FAIL = Path(__file__).parent / "fakes_verify_fail"
FAKES_VERIFY_OK = Path(__file__).parent / "fakes_verify_ok"

CONFIG_YAML = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/core
sources:
  git: { host: github }
lint: { tier1: default }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""


def test_verify_runner_imports():
    import verify_runner  # noqa: F401

    assert hasattr(verify_runner, "run")
    assert hasattr(verify_runner, "main")


def _init_host(tmp_path: Path) -> Path:
    (tmp_path / ".engineering-docs-agent").mkdir()
    (tmp_path / ".engineering-docs-agent" / "config.yml").write_text(CONFIG_YAML)
    state_path = tmp_path / ".engineering-docs-agent" / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "current_run": {
                    "started_at": "2026-05-19T07:00:00Z",
                    "head_sha": "abc123",
                },
            }
        )
    )
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    return state_path


def _invoke(tmp_path: Path, fakes_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "GITHUB_REPOSITORY": "owner/repo"}
    return subprocess.run(
        [
            sys.executable,
            str(VERIFY_RUNNER),
            "--repo-root",
            str(tmp_path),
            "--pr-number",
            "42",
            "--dry-run-subagents",
            str(fakes_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def test_verify_runner_failure_does_not_promote(tmp_path):
    """Failed URLs → rc=1, last_successful_run not written, current_run lives in
    the gitignored sibling (never in committed state.json)."""
    state_path = _init_host(tmp_path)

    r = _invoke(tmp_path, FAKES_VERIFY_FAIL)
    assert r.returncode == 1, r.stderr

    state = json.loads(state_path.read_text())
    assert "last_successful_run" not in state, (
        "verify failure must not promote last_successful_run"
    )
    assert "current_run" not in state, (
        "current_run is ephemeral and must never land in committed state.json"
    )

    sibling = state_path.parent / "current_run.json"
    assert sibling.exists(), "current_run must be preserved in the gitignored sibling"
    assert "current_run" in json.loads(sibling.read_text())


def test_verify_runner_success_promotes(tmp_path):
    """All URLs verified → rc=0, current_run promoted to last_successful_run."""
    state_path = _init_host(tmp_path)

    r = _invoke(tmp_path, FAKES_VERIFY_OK)
    assert r.returncode == 0, r.stderr

    state = json.loads(state_path.read_text())
    assert "last_successful_run" in state
    assert state["last_successful_run"]["pr_number"] == 42
    assert state["last_successful_run"]["head_sha"] == "abc123"
    assert "current_run" not in state, (
        "current_run should be cleared after successful promotion"
    )
    sibling = state_path.parent / "current_run.json"
    assert not sibling.exists(), (
        "sibling must be removed after successful promotion to match in-memory state"
    )


def test_verify_runner_uses_gh_client_for_pr_view(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import verify_runner
    import gh_client

    fake = gh_client.FakeGhClient(
        pr_view_files=gh_client.GhResult(ok=True, value=["docs/site-src/foo.md"]),
    )
    monkeypatch.setattr(verify_runner, "GhClient", lambda *a, **kw: fake)

    _init_host(tmp_path)
    rc = verify_runner.run(tmp_path, 42, dry_run_dir=FAKES_VERIFY_OK)
    assert any(c[0] == "pr_view_files" for c in fake.calls)
    assert rc == 0


def test_verify_runner_uses_cli_pr_number_authoritative(tmp_path):
    """CLI --pr-number is authoritative; state.current_run.pr_number is ignored on promotion."""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import verify_runner

    importlib.reload(verify_runner)

    state_path = _init_host(tmp_path)
    state = json.loads(state_path.read_text())
    state["current_run"]["pr_number"] = 99
    state_path.write_text(json.dumps(state))

    rc = verify_runner.run(tmp_path, 42, dry_run_dir=FAKES_VERIFY_OK)
    assert rc == 0

    state = json.loads(state_path.read_text())
    assert state["last_successful_run"]["pr_number"] == 42, (
        "CLI --pr-number is authoritative"
    )


def test_verify_runner_writes_state_even_on_dispatch_failure(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import verify_runner

    importlib.reload(verify_runner)

    state_path = _init_host(tmp_path)
    # Delete state.json after init so we can detect whether run() re-creates it
    # via try/finally. Without try/finally, the file stays missing because the
    # raise happens before the existing end-of-run write.
    state_path.unlink()

    def raise_on_publish_verifier(name, inputs, *, dry_run_dir, cwd=None):
        if name == "publish-verifier":
            raise RuntimeError("simulated crash")
        return ({"slack_ok": True, "email_ok": True, "errors": []}, [])

    monkeypatch.setattr(verify_runner, "dispatch_validated", raise_on_publish_verifier)

    with pytest.raises(RuntimeError):
        verify_runner.run(tmp_path, 42, dry_run_dir=FAKES_VERIFY_OK)

    # try/finally must have written state.json, even though dispatch raised
    assert state_path.exists(), "state.json must be written via try/finally"
    state = json.loads(state_path.read_text())
    # state was written; current_run not promoted (no last_successful_run)
    assert "last_successful_run" not in state

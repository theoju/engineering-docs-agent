from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

VERIFY_RUNNER = Path(__file__).parent.parent.parent / "scripts" / "verify_runner.py"
FAKES_VERIFY_FAIL = Path(__file__).parent / "fakes_verify_fail"
FAKES_VERIFY_OK = Path(__file__).parent / "fakes_verify_ok"

CONFIG_YAML = """
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
    """Failed URLs → rc=1, last_successful_run not written, current_run kept."""
    state_path = _init_host(tmp_path)

    r = _invoke(tmp_path, FAKES_VERIFY_FAIL)
    assert r.returncode == 1, r.stderr

    state = json.loads(state_path.read_text())
    assert "last_successful_run" not in state, (
        "verify failure must not promote last_successful_run"
    )
    assert "current_run" in state, "current_run should be preserved on failure"


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

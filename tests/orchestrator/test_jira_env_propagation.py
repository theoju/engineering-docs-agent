"""dispatch_subagent must propagate JIRA_EMAIL and JIRA_API_TOKEN into the
subprocess env when they are present in the parent process environment
(CCE-18).

The current implementation at scripts/orchestrator_runner.py:304 does a
full env passthrough (`env={**os.environ, "CLAUDE_STOP_VERIFY": "0"}`),
so these tests pass without code changes — they are regression guards
against a future refactor that switches to an explicit env allowlist.

The 2026-05-21 full-run Jira-enrichment failure was caused by the parent
shell not having JIRA_EMAIL/JIRA_API_TOKEN set, not by dispatch_subagent
stripping them. The operational fix is to set the env vars when running
the orchestrator; the prompt-level fix (graceful degrade) lives in
agents/source-collector.md Step 5 (CCE-18 Task 2).
"""

from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


@pytest.fixture
def stub_run() -> MagicMock:
    """Stub subprocess.run with a successful empty-output result."""
    m = MagicMock()
    m.return_value = MagicMock(
        returncode=0,
        stdout='{"prs": [], "jira_issues": []}',
        stderr="",
    )
    return m


def test_jira_env_propagates_when_set(
    stub_run: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok-123")
    with patch.object(orun.subprocess, "run", stub_run):
        orun.dispatch_subagent(
            "source-collector",
            {"last_sha": "a", "head_sha": "b", "repo": {"owner": "x", "name": "y"}},
            dry_run_dir=None,
            cwd=Path("."),
        )
    assert stub_run.called, "subprocess.run was not invoked"
    kwargs = stub_run.call_args.kwargs
    env = kwargs.get("env", {})
    assert env.get("JIRA_EMAIL") == "user@example.com", env
    assert env.get("JIRA_API_TOKEN") == "tok-123", env
    # CCE-10 invariant: existing env contract still holds.
    assert env.get("CLAUDE_STOP_VERIFY") == "0", env


def test_jira_env_absent_when_unset(
    stub_run: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    with patch.object(orun.subprocess, "run", stub_run):
        orun.dispatch_subagent(
            "source-collector",
            {"last_sha": "a", "head_sha": "b", "repo": {"owner": "x", "name": "y"}},
            dry_run_dir=None,
            cwd=Path("."),
        )
    kwargs = stub_run.call_args.kwargs
    env = kwargs.get("env", {})
    assert "JIRA_EMAIL" not in env or env["JIRA_EMAIL"] == "", env
    assert "JIRA_API_TOKEN" not in env or env["JIRA_API_TOKEN"] == "", env


def test_jira_env_only_one_set(
    stub_run: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If only JIRA_EMAIL is set, JIRA_API_TOKEN stays absent.

    Half-set credentials should NOT be promoted; the agent will detect
    the missing pair and emit jira_auth_missing.
    """
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    with patch.object(orun.subprocess, "run", stub_run):
        orun.dispatch_subagent(
            "source-collector",
            {"last_sha": "a", "head_sha": "b", "repo": {"owner": "x", "name": "y"}},
            dry_run_dir=None,
            cwd=Path("."),
        )
    env = stub_run.call_args.kwargs.get("env", {})
    assert env.get("JIRA_EMAIL") == "user@example.com"
    assert "JIRA_API_TOKEN" not in env or env["JIRA_API_TOKEN"] == ""

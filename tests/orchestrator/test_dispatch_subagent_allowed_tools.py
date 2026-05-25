"""CCE-7: dispatch_subagent must pass only the agent's declared tools
to --allowedTools, not the union of all agents' tools.

Locks the per-agent argv shape for two representative agents:
- pr-summarizer declares only ["Read"] — expect --allowedTools "Read".
- page-author declares ["Read", "Edit", "Write"] — expect those three.

Also pins the "no tools frontmatter" case via a synthetic agent fixture:
when the parser finds no tools list, dispatch omits --allowedTools entirely.
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_agent_tools_cache():
    """Each test starts and ends with a clean frontmatter cache, so tests
    that swap _AGENTS_DIR aren't contaminated by cached real-agent entries."""
    orchestrator_runner._AGENT_TOOLS_CACHE.clear()
    yield
    orchestrator_runner._AGENT_TOOLS_CACHE.clear()


def _fake_run_capture(
    captured: dict, *, stdout: str = '{"ok": true}', returncode: int = 0
):
    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return fake_run


def _allowed_tools_arg(cmd: list[str]) -> str | None:
    """Return the string passed to --allowedTools in this argv, or None if absent."""
    for i, token in enumerate(cmd):
        if token == "--allowedTools" and i + 1 < len(cmd):
            return cmd[i + 1]
    return None


def test_pr_summarizer_gets_only_read(monkeypatch):
    """pr-summarizer's frontmatter declares only Read; argv must reflect that."""
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured))

    orchestrator_runner.dispatch_subagent(
        "pr-summarizer", {"foo": "bar"}, dry_run_dir=None
    )

    arg = _allowed_tools_arg(captured["cmd"])
    assert arg is not None, f"--allowedTools missing from argv; got {captured['cmd']}"
    tools = set(arg.split())
    assert tools == {"Read"}, f"expected just Read; got {tools}"


def test_page_author_gets_declared_three(monkeypatch):
    """page-author declares Read, Edit, Write."""
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured))

    orchestrator_runner.dispatch_subagent(
        "page-author", {"foo": "bar"}, dry_run_dir=None
    )

    arg = _allowed_tools_arg(captured["cmd"])
    assert arg is not None, f"--allowedTools missing from argv; got {captured['cmd']}"
    tools = set(arg.split())
    assert tools == {"Read", "Edit", "Write"}, f"expected Read/Edit/Write; got {tools}"


def test_agent_without_tools_frontmatter_omits_allowed_tools_flag(
    monkeypatch, tmp_path: Path
):
    """When an agent's .md has no tools: list, --allowedTools is omitted entirely.

    Constructs a synthetic agent .md in tmp_path with no tools frontmatter,
    points the loader at the synthetic directory, and asserts the resulting
    argv has no --allowedTools flag at all.
    """
    # Synthetic agent file with no tools: list
    fake_agents_dir = tmp_path / "agents"
    fake_agents_dir.mkdir()
    (fake_agents_dir / "no-tools-agent.md").write_text(
        "---\nname: no-tools-agent\ndescription: A test agent.\nmodel: sonnet\n---\n\n# no-tools-agent\n\nDoes nothing.\n"
    )

    # Point the agents-dir helper at the synthetic dir for this test
    monkeypatch.setattr(orchestrator_runner, "_AGENTS_DIR", fake_agents_dir)

    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured))

    orchestrator_runner.dispatch_subagent(
        "no-tools-agent", {"foo": "bar"}, dry_run_dir=None
    )

    assert "--allowedTools" not in captured["cmd"], (
        f"expected --allowedTools absent for no-tools agent; got {captured['cmd']}"
    )


def test_malformed_tools_frontmatter_raises_clear_error(monkeypatch, tmp_path: Path):
    """When `tools:` is present but not a YAML list (e.g., a string),
    the loader raises ValueError instead of silently falling back to
    the union. Operators see the bug immediately."""
    fake_agents_dir = tmp_path / "agents"
    fake_agents_dir.mkdir()
    (fake_agents_dir / "broken-agent.md").write_text(
        "---\nname: broken-agent\ndescription: bad frontmatter.\nmodel: sonnet\ntools: Read\n---\n\n# broken-agent\n"
    )

    monkeypatch.setattr(orchestrator_runner, "_AGENTS_DIR", fake_agents_dir)

    with pytest.raises(ValueError) as exc_info:
        orchestrator_runner._load_agent_allowed_tools("broken-agent")
    assert "broken-agent" in str(exc_info.value)
    assert "list" in str(exc_info.value).lower()


def test_agent_with_empty_tools_list_passes_empty_allowed_tools(
    monkeypatch, tmp_path: Path
):
    """`tools: []` means 'declared, but no tools' — distinct from no frontmatter.
    The flag must still be passed (as an empty allowlist), not omitted, so an
    intentional lockdown isn't silently downgraded to default permissioning."""
    fake_agents_dir = tmp_path / "agents"
    fake_agents_dir.mkdir()
    (fake_agents_dir / "empty-tools-agent.md").write_text(
        "---\nname: empty-tools-agent\ndescription: locked down.\nmodel: sonnet\ntools: []\n---\n\n# empty-tools-agent\n"
    )
    monkeypatch.setattr(orchestrator_runner, "_AGENTS_DIR", fake_agents_dir)

    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured))

    orchestrator_runner.dispatch_subagent(
        "empty-tools-agent", {"foo": "bar"}, dry_run_dir=None
    )

    assert "--allowedTools" in captured["cmd"], captured["cmd"]
    assert _allowed_tools_arg(captured["cmd"]) == "", (
        f"empty tools list must yield an empty allowlist, got "
        f"{_allowed_tools_arg(captured['cmd'])!r}"
    )

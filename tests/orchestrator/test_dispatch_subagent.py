from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner  # noqa: E402


def _fake_run_capture(captured: dict, *, stdout: str = "{}", returncode: int = 0):
    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return fake_run


def test_dispatch_uses_print_and_agent_flags(monkeypatch):
    """CCE-2: invoke `claude -p <payload> --agent <name>`, not the legacy form."""
    captured: dict = {}
    monkeypatch.setattr(
        subprocess, "run", _fake_run_capture(captured, stdout='{"ok": true}')
    )

    result = orchestrator_runner.dispatch_subagent(
        "source-collector", {"foo": "bar"}, dry_run_dir=None
    )

    assert result == {"ok": True}
    cmd = captured["cmd"]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--agent" in cmd
    assert "source-collector" in cmd

    # Legacy form must not be used.
    assert cmd[:2] != ["claude", "agent"], f"legacy positional subcommand: {cmd}"
    assert "--input" not in cmd, f"legacy --input flag: {cmd}"


def test_dispatch_passes_inputs_as_prompt_payload(monkeypatch):
    """The inputs dict is serialized as the -p prompt argument."""
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured, stdout="{}"))

    orchestrator_runner.dispatch_subagent(
        "page-author", {"target_path": "docs/x.md", "lens": "core"}, dry_run_dir=None
    )

    cmd = captured["cmd"]
    p_index = cmd.index("-p")
    payload = cmd[p_index + 1]
    assert json.loads(payload) == {"target_path": "docs/x.md", "lens": "core"}


def test_dispatch_returns_none_on_missing_binary(monkeypatch):
    """FileNotFoundError (claude binary missing) → None, unchanged contract."""

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert (
        orchestrator_runner.dispatch_subagent("notifier", {}, dry_run_dir=None) is None
    )


def test_dispatch_returns_none_on_nonzero_exit(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured, returncode=1))
    assert (
        orchestrator_runner.dispatch_subagent("notifier", {}, dry_run_dir=None) is None
    )


def test_dispatch_returns_none_on_unparseable_json(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        subprocess, "run", _fake_run_capture(captured, stdout="not json")
    )
    assert (
        orchestrator_runner.dispatch_subagent("notifier", {}, dry_run_dir=None) is None
    )


def test_dispatch_returns_none_on_empty_stdout(monkeypatch):
    """Empty/whitespace stdout → None (locks in the .strip() guard)."""
    for empty in ("", "   ", "\n\n"):
        captured: dict = {}
        monkeypatch.setattr(
            subprocess, "run", _fake_run_capture(captured, stdout=empty)
        )
        assert (
            orchestrator_runner.dispatch_subagent("notifier", {}, dry_run_dir=None)
            is None
        ), f"empty stdout {empty!r} should return None"

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


def test_dispatch_embeds_inputs_inside_execution_framing(monkeypatch):
    """CCE-3 A: prompt wraps the JSON in <inputs>...</inputs> with execution framing.

    Locks the byte-for-byte payload contract: a future refactor that reformats
    the JSON (sorting keys, pretty-printing, escape changes) would break this.
    Also pins specific framing phrases so a weakening edit (dropping the
    no-prose / no-markdown / execute-the-Job instructions) is caught here
    rather than at runtime against a live LLM.
    """
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured, stdout="{}"))

    inputs = {"target_path": "docs/x.md", "lens": "core"}
    orchestrator_runner.dispatch_subagent("page-author", inputs, dry_run_dir=None)

    cmd = captured["cmd"]
    prompt = cmd[cmd.index("-p") + 1]

    # Framing markers present.
    assert "<inputs>" in prompt and "</inputs>" in prompt

    # Pin specific framing phrases — a weakening edit fails the test, not the LLM.
    for required_phrase in (
        "Execute the Job",
        "Return ONLY",
        "no prose",
        "no markdown fences",
        "no clarifying questions",
    ):
        assert required_phrase in prompt, (
            f"framing weakened: missing {required_phrase!r}"
        )

    # Payload must appear byte-for-byte (json.dumps output, unmodified).
    expected_payload = json.dumps(inputs)
    assert expected_payload in prompt, (
        "payload was transformed inside framing (re-serialized?)"
    )

    # And it must appear between the markers, not elsewhere.
    start = prompt.index("<inputs>") + len("<inputs>")
    end = prompt.index("</inputs>")
    assert expected_payload in prompt[start:end]


def test_dispatch_threads_cwd_to_subprocess(monkeypatch, tmp_path):
    """CCE-3 B: when cwd is passed, subprocess.run receives it."""
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured, stdout="{}"))

    orchestrator_runner.dispatch_subagent(
        "notifier", {"x": 1}, dry_run_dir=None, cwd=tmp_path
    )

    assert captured["kwargs"].get("cwd") == str(tmp_path)


def test_dispatch_omits_cwd_when_not_provided(monkeypatch):
    """Default behavior: no cwd kwarg means subprocess inherits parent CWD."""
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured, stdout="{}"))

    orchestrator_runner.dispatch_subagent("notifier", {}, dry_run_dir=None)

    assert "cwd" not in captured["kwargs"] or captured["kwargs"].get("cwd") is None


def test_dispatch_auto_passes_plugin_dir(monkeypatch):
    """CCE-3 C1: argv contains --plugin-dir pointing at the plugin root."""
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured, stdout="{}"))

    orchestrator_runner.dispatch_subagent("notifier", {}, dry_run_dir=None)

    cmd = captured["cmd"]
    assert "--plugin-dir" in cmd
    plugin_dir = Path(cmd[cmd.index("--plugin-dir") + 1])
    # Plugin root is two levels up from orchestrator_runner.py (scripts/ → repo root).
    expected = Path(orchestrator_runner.__file__).resolve().parent.parent
    assert plugin_dir.resolve() == expected
    # And it should actually contain the agents directory.
    assert (plugin_dir / "agents").is_dir()


def test_dispatch_passes_per_agent_allowed_tools(monkeypatch):
    """CCE-7: --allowedTools reflects only the agent's declared tools, not the union.

    notifier declares only Bash in its frontmatter, so the argv must contain
    exactly --allowedTools "Bash" — not the former union of all agents' tools.
    """
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured, stdout="{}"))

    orchestrator_runner.dispatch_subagent("notifier", {}, dry_run_dir=None)

    cmd = captured["cmd"]
    assert "--allowedTools" in cmd
    tools_arg = cmd[cmd.index("--allowedTools") + 1]
    assert tools_arg == "Bash", (
        f"expected notifier to get only Bash; got --allowedTools={tools_arg}"
    )


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


def test_dispatch_passes_setting_sources_flag(monkeypatch):
    """CCE-15: dispatch must pass `--setting-sources project,local` so
    the user-level settings.json (where the explanatory-output-style
    plugin is enabled by default) is skipped. Without this, the plugin's
    SessionStart hook injects "★ Insight ─" prose into the subagent's
    context, breaking _extract_final_assistant_text parsing as observed
    in CCE-14 Run 4. Unlike --bare (originally tried but rejected
    because it disables OAuth), this preserves keychain authentication.
    """
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured, stdout="{}"))

    orchestrator_runner.dispatch_subagent(
        "source-collector", {"foo": "bar"}, dry_run_dir=None
    )

    cmd = captured["cmd"]
    assert "--setting-sources" in cmd, f"--setting-sources not in argv: {cmd}"
    idx = cmd.index("--setting-sources")
    assert cmd[idx + 1] == "project,local", (
        f"--setting-sources value must be 'project,local': cmd[{idx + 1}] = {cmd[idx + 1]!r}"
    )
    # The flag must appear before -p so it governs the whole invocation.
    assert idx < cmd.index("-p"), f"--setting-sources must precede -p: {cmd}"

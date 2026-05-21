"""CCE-10: dispatch_subagent passes CLAUDE_STOP_VERIFY=0 to subprocess env so
the global stop-verify hook does not contaminate subagent stdout with a
"Verification statement:" prose preamble that breaks json.loads()."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


class _FakeCompleted:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_dispatch_subagent_sets_stop_verify_off(monkeypatch):
    import orchestrator_runner as runner

    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _FakeCompleted(stdout='{"prs": [], "jira_issues": []}')

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.delenv("DOCS_AGENT_DEBUG_DIR", raising=False)

    result = runner.dispatch_subagent(
        "source-collector",
        {"last_sha": "abc", "head_sha": "def", "repo": {"owner": "x", "name": "y"}},
        dry_run_dir=None,
    )

    assert result == {"prs": [], "jira_issues": []}

    env = captured["kwargs"].get("env")
    assert env is not None, (
        "dispatch_subagent must pass an explicit env dict to subprocess.run "
        "so CLAUDE_STOP_VERIFY=0 reaches the child Claude session"
    )
    assert env.get("CLAUDE_STOP_VERIFY") == "0", (
        "env must set CLAUDE_STOP_VERIFY=0 to disable the stop-verify hook "
        "(see ~/.claude/hooks/stop-verify.sh:22)"
    )
    assert env.get("PATH") == os.environ.get("PATH"), (
        "env should extend os.environ via {**os.environ, ...} overlay, not replace it"
    )

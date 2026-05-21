"""CCE-9: dispatch_subagent writes raw stdout/stderr/prompt/meta to
$DOCS_AGENT_DEBUG_DIR when set; is a no-op when unset."""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


class _FakeCompleted:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_debug_capture_writes_files_when_env_var_set(tmp_path, monkeypatch):
    import orchestrator_runner as runner

    fake_stdout = '{"prs": [], "jira_issues": []}'
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **kw: _FakeCompleted(stdout=fake_stdout),
    )
    monkeypatch.setenv("DOCS_AGENT_DEBUG_DIR", str(tmp_path))

    result = runner.dispatch_subagent(
        "source-collector",
        {"last_sha": "", "head_sha": "abc", "repo": {"owner": "o", "name": "n"}},
        dry_run_dir=None,
    )

    # CCE-12: with DOCS_AGENT_DEBUG_DIR set the dispatcher uses stream-json.
    # This test's fake stdout is a single JSON object (not real NDJSON), so
    # no assistant events are found and the canonical text is empty -> None.
    # The capture artifacts are still written for forensics regardless.
    assert result is None

    captured = sorted(tmp_path.iterdir())
    suffixes = {p.name.split(".", 1)[1] for p in captured}
    assert suffixes == {
        "prompt.txt",
        "stdout.txt",
        "stderr.txt",
        "stream.jsonl",
        "meta.json",
    }, f"expected 5 capture artifacts; got {sorted(p.name for p in captured)}"

    # CCE-12: in stream-json mode, stdout.txt holds the extracted final
    # assistant text. Our fake CompletedProcess used a single JSON object
    # as stdout (not real NDJSON), so the parser sees zero assistant events
    # and the extracted text is empty.
    stdout_file = next(p for p in captured if p.name.endswith(".stdout.txt"))
    assert stdout_file.read_text() == ""

    # Raw fake stdout is preserved in stream.jsonl for forensics.
    stream_file = next(p for p in captured if p.name.endswith(".stream.jsonl"))
    assert stream_file.read_text() == fake_stdout

    meta_file = next(p for p in captured if p.name.endswith(".meta.json"))
    meta = json.loads(meta_file.read_text())
    assert meta["returncode"] == 0
    assert "source-collector" in meta["argv"]


def test_debug_capture_noop_when_env_var_unset(tmp_path, monkeypatch):
    import orchestrator_runner as runner

    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **kw: _FakeCompleted(stdout='{"prs": [], "jira_issues": []}'),
    )
    monkeypatch.delenv("DOCS_AGENT_DEBUG_DIR", raising=False)

    result = runner.dispatch_subagent(
        "source-collector",
        {"last_sha": "", "head_sha": "abc", "repo": {"owner": "o", "name": "n"}},
        dry_run_dir=None,
    )

    assert result == {"prs": [], "jira_issues": []}
    assert list(tmp_path.iterdir()) == [], (
        f"no files should be written when DOCS_AGENT_DEBUG_DIR is unset; "
        f"got {[p.name for p in tmp_path.iterdir()]}"
    )

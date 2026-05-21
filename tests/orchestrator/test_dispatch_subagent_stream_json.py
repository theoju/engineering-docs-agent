"""CCE-12: stream-json dispatch path — parse NDJSON, extract final text,
summarize tool use, persist forensics artifacts."""

from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cce12_stream_json"


def _load_events(fixture_name: str) -> list[dict]:
    path = _FIXTURE_DIR / fixture_name
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def test_extract_final_assistant_text_with_tools_fixture():
    import orchestrator_runner as runner

    events = _load_events("source_collector_with_tools.jsonl")
    text = runner._extract_final_assistant_text(events)

    parsed = json.loads(text)
    assert parsed == {
        "prs": [{"number": 42, "url": "https://example.com/pr/42", "title": "Add foo"}],
        "jira_issues": [],
    }


def test_extract_final_assistant_text_no_assistant_returns_empty():
    import orchestrator_runner as runner

    events = [
        {"type": "system", "subtype": "init"},
        {"type": "result", "subtype": "success"},
    ]
    assert runner._extract_final_assistant_text(events) == ""


def test_extract_final_assistant_text_concatenates_multi_text_blocks():
    import orchestrator_runner as runner

    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": '{"prs":'},
                    {"type": "tool_use", "id": "tu_x", "name": "Bash", "input": {}},
                    {"type": "text", "text": '[],"jira_issues":[]}'},
                ],
            },
        }
    ]
    assert runner._extract_final_assistant_text(events) == (
        '{"prs":[],"jira_issues":[]}'
    )


def test_extract_final_assistant_text_uses_last_assistant_only():
    import orchestrator_runner as runner

    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "first"}],
            },
        },
        {"type": "user", "message": {"role": "user", "content": []}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "last"}],
            },
        },
    ]
    assert runner._extract_final_assistant_text(events) == "last"


def test_summarize_tool_use_with_tools_fixture():
    import orchestrator_runner as runner

    events = _load_events("source_collector_with_tools.jsonl")
    summary = runner._summarize_tool_use(events)

    assert summary["total_calls"] == 2
    assert summary["by_name"] == {"Bash": 2}
    assert summary["calls_truncated"] is False
    assert summary["turns"] == 3
    assert summary["stop_reason"] == "end_turn"
    assert summary["duration_ms"] == 18742

    assert len(summary["calls"]) == 2
    first = summary["calls"][0]
    assert first["name"] == "Bash"
    assert "gh pr list" in first["input_preview"]
    assert first["is_error"] is False
    assert first["result_chars"] > 0


def test_summarize_tool_use_no_tools_fixture():
    import orchestrator_runner as runner

    events = _load_events("source_collector_no_tools.jsonl")
    summary = runner._summarize_tool_use(events)

    assert summary["total_calls"] == 0
    assert summary["by_name"] == {}
    assert summary["calls"] == []
    assert summary["calls_truncated"] is False
    assert summary["turns"] == 1
    assert summary["stop_reason"] == "end_turn"


def test_summarize_tool_use_flags_errored_tool_result():
    import orchestrator_runner as runner

    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_err",
                        "name": "Bash",
                        "input": {"command": "gh pr list --bad"},
                    },
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_err",
                        "content": "error: unknown flag --bad",
                        "is_error": True,
                    },
                ],
            },
        },
        {
            "type": "result",
            "subtype": "error",
            "stop_reason": "tool_error",
            "num_turns": 1,
            "duration_ms": 412,
        },
    ]
    summary = runner._summarize_tool_use(events)
    assert summary["total_calls"] == 1
    assert summary["calls"][0]["is_error"] is True
    assert summary["stop_reason"] == "tool_error"


def test_summarize_tool_use_caps_calls_at_50_and_sets_truncated():
    import orchestrator_runner as runner

    # 51 tool_use blocks in a single assistant message — should cap at 50.
    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"tu_{i:03d}",
                        "name": "Bash",
                        "input": {"command": f"echo {i}"},
                    }
                    for i in range(51)
                ],
            },
        },
        {
            "type": "result",
            "subtype": "success",
            "stop_reason": "end_turn",
            "num_turns": 1,
            "duration_ms": 999,
        },
    ]
    summary = runner._summarize_tool_use(events)
    assert summary["total_calls"] == 51
    assert len(summary["calls"]) == 50
    assert summary["calls_truncated"] is True
    assert summary["by_name"] == {"Bash": 51}


class _FakeCompleted:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_dispatch_uses_stream_json_when_debug_dir_set(tmp_path, monkeypatch):
    import orchestrator_runner as runner

    fixture = _FIXTURE_DIR / "source_collector_with_tools.jsonl"
    ndjson_stdout = fixture.read_text()

    captured_argv: list[list[str]] = []

    def fake_run(*args, **kwargs):
        captured_argv.append(list(args[0]))
        return _FakeCompleted(stdout=ndjson_stdout)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setenv("DOCS_AGENT_DEBUG_DIR", str(tmp_path))

    result = runner.dispatch_subagent(
        "source-collector",
        {"last_sha": "x", "head_sha": "y", "repo": {"owner": "o", "name": "n"}},
        dry_run_dir=None,
    )

    # 1. Caller contract preserved: parsed dict comes from the final assistant text.
    assert result == {
        "prs": [{"number": 42, "url": "https://example.com/pr/42", "title": "Add foo"}],
        "jira_issues": [],
    }

    # 2. Subprocess argv carries the stream-json flags.
    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv

    # 3. All five forensics artifacts written.
    artifacts = sorted(p.name for p in tmp_path.iterdir())
    suffixes = {name.split(".", 1)[1] for name in artifacts}
    assert suffixes == {
        "prompt.txt",
        "stdout.txt",
        "stderr.txt",
        "stream.jsonl",
        "meta.json",
    }, f"got {artifacts}"

    # 4. stdout.txt = extracted canonical JSON (caller view), NOT raw NDJSON.
    stdout_file = next(p for p in tmp_path.iterdir() if p.name.endswith(".stdout.txt"))
    assert json.loads(stdout_file.read_text()) == result

    # 5. stream.jsonl = raw NDJSON bytes (forensics).
    stream_file = next(
        p for p in tmp_path.iterdir() if p.name.endswith(".stream.jsonl")
    )
    assert stream_file.read_text() == ndjson_stdout

    # 6. meta.json includes the tool_use summary block.
    meta_file = next(p for p in tmp_path.iterdir() if p.name.endswith(".meta.json"))
    meta = json.loads(meta_file.read_text())
    assert meta["returncode"] == 0
    assert "source-collector" in meta["argv"]
    assert meta["tool_use"]["total_calls"] == 2
    assert meta["tool_use"]["by_name"] == {"Bash": 2}
    assert meta["tool_use"]["stop_reason"] == "end_turn"


def test_dispatch_uses_simple_print_when_debug_dir_unset(tmp_path, monkeypatch):
    import orchestrator_runner as runner

    captured_argv: list[list[str]] = []

    def fake_run(*args, **kwargs):
        captured_argv.append(list(args[0]))
        return _FakeCompleted(stdout='{"prs":[],"jira_issues":[]}')

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.delenv("DOCS_AGENT_DEBUG_DIR", raising=False)

    result = runner.dispatch_subagent(
        "source-collector",
        {"last_sha": "x", "head_sha": "y", "repo": {"owner": "o", "name": "n"}},
        dry_run_dir=None,
    )

    assert result == {"prs": [], "jira_issues": []}

    # No stream-json flags in argv when gate is off.
    argv = captured_argv[0]
    assert "--output-format" not in argv
    assert "--verbose" not in argv

    # No debug artifacts written.
    assert list(tmp_path.iterdir()) == []


def test_extract_final_assistant_text_skips_pure_tool_use_final_turn():
    """If the LAST assistant turn is purely tool_use blocks, prefer the
    earlier assistant turn that had text. Forward-compat hardening — CCE-14.
    """
    import orchestrator_runner as runner

    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "earlier answer with text"}],
            },
        },
        {
            "type": "user",
            "message": {"role": "user", "content": []},
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_last",
                        "name": "Bash",
                        "input": {"command": "echo done"},
                    },
                ],
            },
        },
    ]
    assert runner._extract_final_assistant_text(events) == "earlier answer with text"


def test_extract_final_assistant_text_all_tool_only_returns_empty():
    """If EVERY assistant turn is purely tool_use blocks (no text anywhere
    in any assistant turn), return "". Distinct from the no-assistant-events
    case — assistant turns DO exist, they just have no text content.
    Closes the coverage gap flagged in CCE-14 Stage 4 review.
    """
    import orchestrator_runner as runner

    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_a",
                        "name": "Bash",
                        "input": {"command": "gh pr list"},
                    },
                ],
            },
        },
        {
            "type": "user",
            "message": {"role": "user", "content": []},
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_b",
                        "name": "Bash",
                        "input": {"command": "echo done"},
                    },
                ],
            },
        },
    ]
    assert runner._extract_final_assistant_text(events) == ""

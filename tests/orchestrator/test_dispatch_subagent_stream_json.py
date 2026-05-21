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

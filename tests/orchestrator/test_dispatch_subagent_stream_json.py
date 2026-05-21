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

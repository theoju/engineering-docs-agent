from __future__ import annotations
import json
from pathlib import Path
from jsonschema import validate, ValidationError
import pytest

SCHEMA = json.loads(
    (
        Path(__file__).parent.parent.parent / "templates" / "state.schema.json"
    ).read_text()
)


def test_minimal_valid():
    validate({"version": "1"}, SCHEMA)


def test_full_state_valid():
    state = {
        "version": "1",
        "last_successful_run": {
            "completed_at": "2026-05-19T07:00:00Z",
            "head_sha": "abc",
            "pr_number": 142,
        },
        "current_run": {
            "started_at": "2026-05-20T07:00:00Z",
            "head_sha": "def",
            "partial": False,
            "partial_reasons": [],
            "pr_number": None,
        },
        "dismissed_gap_flags": {"x/y#1": "dismissed"},
        "cursors": {"jira_last_updated": "2026-05-19T06:58:00Z"},
    }
    validate(state, SCHEMA)


def test_missing_version_rejected():
    with pytest.raises(ValidationError):
        validate({}, SCHEMA)


def test_current_run_requires_started_at():
    bad = {"version": "1", "current_run": {"head_sha": "x"}}
    with pytest.raises(ValidationError):
        validate(bad, SCHEMA)

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
        "dismissed_gap_flags": {"x/y#1": "dismissed"},
        "cursors": {"jira_last_updated": "2026-05-19T06:58:00Z"},
    }
    validate(state, SCHEMA)


def test_missing_version_rejected():
    with pytest.raises(ValidationError):
        validate({}, SCHEMA)


def test_schema_accepts_state_without_current_run():
    state = {
        "version": "1",
        "last_successful_run": {
            "head_sha": "abc",
            "completed_at": "2026-05-28T00:00:00+00:00",
        },
    }
    validate(state, SCHEMA)


def test_schema_permissive_to_legacy_current_run():
    """Pre-CCE-40 state files may still carry current_run on disk. The
    schema must not reject them — the runner strips current_run at load."""
    state = {
        "version": "1",
        "last_successful_run": {"head_sha": "abc"},
        "current_run": {"started_at": "2026-05-28T00:00:00+00:00"},
    }
    validate(state, SCHEMA)

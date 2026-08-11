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


# ---------------------------------------------------------------------------
# CCE-140: skipped_prs / deferral_counts
# ---------------------------------------------------------------------------


def test_skipped_prs_and_deferral_counts_validate():
    """CCE-140. Shape follows the dismissed_gap_flags precedent: PR identity
    is the `{owner}/{name}#{pr}` string the runner already builds at
    orchestrator_runner.py:1901."""
    state = {
        "version": "1",
        "last_successful_run": {
            "head_sha": "abc",
            "completed_at": "2026-08-11T03:00:00+00:00",
        },
        "deferral_counts": {"o/r#5": 2, "o/r#6": 0},
        "skipped_prs": [
            {
                "pr": "o/r#4",
                "url": "https://github.com/o/r/pull/4",
                "pages": ["core/connectors/beta.md"],
                "deferrals": 3,
                "skipped_at": "2026-08-11T03:00:00+00:00",
            }
        ],
    }
    validate(state, SCHEMA)


def test_skipped_pr_entry_requires_its_identity_fields():
    with pytest.raises(ValidationError):
        validate({"version": "1", "skipped_prs": [{"pages": ["a.md"]}]}, SCHEMA)


def test_deferral_counts_rejects_a_negative():
    with pytest.raises(ValidationError):
        validate({"version": "1", "deferral_counts": {"o/r#1": -1}}, SCHEMA)


def test_deferral_counts_rejects_a_non_integer():
    with pytest.raises(ValidationError):
        validate({"version": "1", "deferral_counts": {"o/r#1": "two"}}, SCHEMA)


def test_pre_cce140_state_still_validates():
    """Back-compat, both directions. A state.json written before CCE-140 has
    neither key; the root declares required:['version'] and no
    additionalProperties:false, so nothing about the old file becomes invalid
    and there is no migration step. The reverse also holds — a new-format file
    validates against the OLD schema — which matters because the plugin is
    consumed at ref: main with no release step."""
    legacy = {"version": "1", "dismissed_gap_flags": {}, "cursors": {}}
    validate(legacy, SCHEMA)
    assert "skipped_prs" not in legacy
    assert "deferral_counts" not in legacy

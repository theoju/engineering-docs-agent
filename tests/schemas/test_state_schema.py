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


def test_pre_cce140_state_validates_against_the_new_schema():
    """Forward direction: a state.json written before CCE-140 has neither new
    key, and the root declares required:['version'] with no
    additionalProperties:false, so nothing about the old file becomes invalid
    and no migration step is needed."""
    legacy = {"version": "1", "dismissed_gap_flags": {}, "cursors": {}}
    validate(legacy, SCHEMA)


def test_post_cce140_state_validates_against_the_old_schema():
    """Reverse direction, which is the one that can actually bite.

    The plugin is consumed at `ref: main` with no release step, so a host can
    run yesterday's checkout against a state.json that today's run wrote. If
    the old schema rejected the new keys, that host hard-fails on load --
    `load_state_validated` raises StateError -- holding a state file it cannot
    repair by rolling back.

    The claim previously lived only in prose; the assertion beside it checked
    `"skipped_prs" not in legacy` against a dict literal declared two lines
    above, which cannot fail. Here the pre-CCE-140 schema is reconstructed by
    removing exactly the two property declarations this change added, and a
    fully-populated new-format state is validated against it. It passes only
    because the root carries no `additionalProperties: false` -- adding one
    later breaks this test, which is the point.
    """
    old_schema = json.loads(json.dumps(SCHEMA))
    removed = [
        old_schema["properties"].pop(k, None)
        for k in ("deferral_counts", "skipped_prs")
    ]
    assert all(r is not None for r in removed), (
        "both CCE-140 keys must be declared in the current schema, or this "
        "test is reconstructing something other than the old schema"
    )
    modern = {
        "version": "1",
        "last_successful_run": {"head_sha": "a" * 40},
        "deferral_counts": {"o/r#3": 2},
        "skipped_prs": [
            {
                "pr": "o/r#3",
                "url": "https://github.com/o/r/pull/3",
                "pages": ["core/x.md"],
                "deferrals": 3,
                "skipped_at": "2026-08-10T07:00:00Z",
            }
        ],
    }
    validate(modern, old_schema)

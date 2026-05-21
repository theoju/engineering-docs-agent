from __future__ import annotations
import json
from pathlib import Path
from jsonschema import validate, ValidationError
import pytest

SCHEMA = json.loads(
    (
        Path(__file__).parent.parent.parent
        / "agents"
        / "schemas"
        / "source_collector.schema.json"
    ).read_text()
)


def test_canonical_empty_shape_still_passes():
    """Regression guard: the empty {prs:[], jira_issues:[]} shape that the
    agent emits when last_sha..HEAD has zero merged PRs must still pass
    after additionalProperties:false is added.
    """
    validate({"prs": [], "jira_issues": []}, SCHEMA)


def test_full_pr_with_all_known_fields_still_passes():
    """Regression guard: the most complex canonical output observed in
    production (CCE-14 Run 1's stdout) must still pass. Tightening the
    schema must not reject any field listed in `properties`.
    """
    full = {
        "prs": [
            {
                "number": 9,
                "url": "https://github.com/theoju/engineering-docs-agent/pull/9",
                "title": "feat(CCE-12): source-collector tool-use diagnostics",
                "body": "## Summary\n\n- Adds a debug-dir-gated stream-json path...",
                "merge_sha": "f0e774c34ba7afdc308434d5321285a7256578ab",
                "merged_at": "2026-05-21T06:01:49Z",
                "author": "theoju",
                "files": [
                    {
                        "path": "scripts/orchestrator_runner.py",
                        "additions": 145,
                        "deletions": 13,
                        "changeType": "MODIFIED",
                    }
                ],
                "labels": [],
                "jira_keys": ["CCE-12", "CCE-13", "CCE-10"],
            }
        ],
        "jira_issues": [],
    }
    validate(full, SCHEMA)


def test_phantom_top_level_field_rejected():
    """CCE-15 Mode 1: the agent has been observed emitting
    {"prs":[], "jira_issues":[], "commits":[]} — a phantom `commits`
    field that doesn't exist in the schema. This MUST be rejected so
    the orchestrator sees schema_invalid instead of silently accepting
    it as an empty-success run.
    """
    bad = {"prs": [], "jira_issues": [], "commits": []}
    with pytest.raises(ValidationError) as exc_info:
        validate(bad, SCHEMA)
    assert "commits" in str(exc_info.value)


def test_phantom_per_pr_item_field_rejected():
    """CCE-15: tighten per-PR items too. If an agent invents fields
    inside a PR object (e.g. `extra`, `status`, `summary`), they must
    be rejected. Otherwise the orchestrator could receive misleading
    auxiliary data the downstream agents don't know how to consume.
    """
    bad = {
        "prs": [{"number": 1, "url": "https://example.com/pr/1", "extra": "x"}],
        "jira_issues": [],
    }
    with pytest.raises(ValidationError) as exc_info:
        validate(bad, SCHEMA)
    assert "extra" in str(exc_info.value)

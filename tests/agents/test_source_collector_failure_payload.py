# tests/agents/test_source_collector_failure_payload.py
"""CCE-177 (change C): source-collector's documented failure payloads must
validate against its own schema.

`## Failure handling` bullet 3 told the agent to return
`{"error": "git_unrecoverable: <reason>"}` — an object with neither `prs`
nor `jira_issues`, both `required`. An agent that followed the contract
produced the byte-identical `'prs' is a required property` that a payload
truncated by the output-token ceiling produces, so the logs could not tell
the two apart.

`tests/agents/test_schema_md_sync.py` cannot catch this: it compares only
the `## Output schema (canonical)` fenced block, not prose elsewhere in the
file. This test reads the shape out of the prose itself, so a future edit
that reintroduces a schema-invalid failure payload fails here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest

_ROOT = Path(__file__).parent.parent.parent
AGENT_MD = _ROOT / "agents" / "source-collector.md"
SCHEMA_PATH = _ROOT / "agents" / "schemas" / "source_collector.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def failure_handling() -> str:
    body = AGENT_MD.read_text()
    start = body.index("## Failure handling")
    return body[start:]


def _bullet(section: str, token: str) -> str:
    matches = [ln for ln in section.splitlines() if token in ln]
    assert len(matches) == 1, f"expected exactly one {token!r} bullet, got {matches}"
    return matches[0]


def test_git_unrecoverable_payload_validates(schema: dict, failure_handling: str):
    """The shape the contract tells the agent to emit, parsed out of the
    contract and validated against the contract's own schema."""
    bullet = _bullet(failure_handling, "git_unrecoverable")
    spans = re.findall(r"`(\{.*?\})`", bullet)
    assert len(spans) == 1, f"expected one JSON object in the bullet, got {spans}"

    payload = json.loads(spans[0])
    jsonschema.validate(payload, schema)
    assert payload["prs"] == []
    assert payload["jira_issues"] == []
    assert payload["partial"] is True
    assert payload["error"].startswith("git_unrecoverable")


def test_git_rate_limit_bullet_names_both_required_arrays(failure_handling: str):
    """Bullet 1 carries `[...partial...]` placeholders, so it cannot be
    parsed — but it must still name both required properties."""
    bullet = _bullet(failure_handling, "git_rate_limit")
    assert '"prs"' in bullet
    assert '"jira_issues"' in bullet


def test_canonical_error_shape_validates(schema: dict):
    """The same shape as a literal, so a doc-parsing change cannot make the
    schema assertion above vacuous."""
    jsonschema.validate(
        {
            "prs": [],
            "jira_issues": [],
            "partial": True,
            "error": "git_unrecoverable: api timeout after 3 retries",
        },
        schema,
    )


def test_error_only_object_is_rejected_by_the_schema(schema: dict):
    """Why change C exists: the old documented shape fails validation, and a
    source-collector `schema_invalid` is blind (CCE-144)."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"error": "git_unrecoverable: disk full"}, schema)

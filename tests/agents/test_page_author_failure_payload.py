# tests/agents/test_page_author_failure_payload.py
"""CCE-180: page-author's documented failure payload must validate.

The page-authoring loop in ``scripts/orchestrator_runner.py`` reads only
``ok`` and ``error`` from a page-author result — the path it uses is its own
``rel_posix``, never the agent's ``path``. Typing ``path``/``action``/
``diff_summary`` as bare strings made a *present* null fatal at schema
validation, and validation runs first: ``dispatch_verified`` returned None,
the run recorded ``page_author_invalid`` (degraded, holds the PR out of the
advance cursor), and the graceful ``page_author_error`` branch was never
reached.

Same shape as CCE-125's gap-detector fix: present-null is first-class, an
absent key or a wrong non-null type still fails loud.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = (
    Path(__file__).parent.parent.parent
    / "agents"
    / "schemas"
    / "page_author.schema.json"
)

NULLABLE_FIELDS = ["path", "action", "diff_summary"]


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def test_documented_failure_payload_validates(schema: dict) -> None:
    """The exact shape agents/page-author.md tells the agent to return."""
    jsonschema.validate(
        {"ok": False, "error": "path_not_agent_editable", "path": None}, schema
    )


@pytest.mark.parametrize("field", NULLABLE_FIELDS)
def test_present_null_is_accepted(schema: dict, field: str) -> None:
    jsonschema.validate({"ok": False, "error": "unusable", field: None}, schema)


@pytest.mark.parametrize("field", NULLABLE_FIELDS)
def test_wrong_non_null_type_still_fails(schema: dict, field: str) -> None:
    """Genuine agent malfunction must stay loud — only null is forgiven."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"ok": True, field: 42}, schema)


def test_missing_ok_still_fails(schema: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"path": "docs/site-src/core/x.md"}, schema)


def test_ok_true_payload_still_validates(schema: dict) -> None:
    jsonschema.validate(
        {
            "path": "docs/site-src/core/connectors.md",
            "action": "edit",
            "diff_summary": "Added 2 paragraphs.",
            "ok": True,
        },
        schema,
    )

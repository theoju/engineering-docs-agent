"""Schema enforcement for pr-summarizer output (CCE-17).

The schema enforces UNIVERSAL structural rules:
- page_hint must be a relative (no leading slash) .md path
- page_hint must not end in a source-code extension (.py, .json, .yml, etc.)
- lens must be one of ["core", "superpowers"]
- additionalProperties is false at root and on doc_targets items

Host-config-specific rules (e.g., the production sandbox prefix
`_agent-sandbox/`) live in the agent prompt and are enforced at runtime
by the orchestrator's `agent_editable_paths` filter, not by the schema.
That separation keeps the canonical schema portable across host configs.
"""

from __future__ import annotations
import json
from pathlib import Path
import pytest
from jsonschema import Draft7Validator, ValidationError

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "agents"
    / "schemas"
    / "pr_summarizer.schema.json"
)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft7Validator:
    return Draft7Validator(schema)


def test_minimal_valid(validator: Draft7Validator) -> None:
    doc = {"pr_number": 1, "doc_targets": []}
    validator.validate(doc)


def test_create_lens_relative_md_accepted(validator: Draft7Validator) -> None:
    """The host-config sandbox prefix is documented in the prompt, not the schema."""
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "core", "action": "create", "page_hint": "_agent-sandbox/foo.md"}
        ],
    }
    validator.validate(doc)


def test_create_rejects_leading_slash(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "core", "action": "create", "page_hint": "/abs/path.md"}
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)


def test_create_rejects_python_source(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "create",
                "page_hint": "scripts/orchestrator_runner.py",
            }
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)


def test_create_rejects_json_source(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "create",
                "page_hint": ".claude-plugin/plugin.json",
            }
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)


def test_create_rejects_missing_md_extension(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [{"lens": "core", "action": "create", "page_hint": "CHANGELOG"}],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)


def test_edit_allows_lens_relative_md(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "superpowers",
                "action": "edit",
                "page_hint": "measurements/2026-05-20-cce12.md",
            }
        ],
    }
    validator.validate(doc)


def test_edit_rejects_source_extension(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "edit",
                "page_hint": "scripts/orchestrator_runner.py",
            }
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)


def test_unknown_lens_rejected(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "archive", "action": "edit", "page_hint": "specs/foo.md"}
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)


def test_extra_top_level_field_rejected(validator: Draft7Validator) -> None:
    doc = {"pr_number": 1, "doc_targets": [], "bogus": True}
    with pytest.raises(ValidationError):
        validator.validate(doc)


def test_extra_doc_target_field_rejected(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "create",
                "page_hint": "_agent-sandbox/foo.md",
                "extra": 1,
            }
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)

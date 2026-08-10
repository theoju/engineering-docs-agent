"""Schema enforcement for pr-summarizer output (CCE-17).

The schema enforces UNIVERSAL structural rules:
- page_hint must be a relative (no leading slash) .md path
- page_hint must not end in a source-code extension (.py, .json, .yml, etc.)
- lens must be a non-empty string (any host-defined lens name is valid)
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


def test_create_lens_relative_semantic_path_accepted(
    validator: Draft7Validator,
) -> None:
    """The host-config sandbox prefix is documented in the prompt, not the schema."""
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "core", "action": "create", "page_hint": "operations/foo.md"}
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
                "lens": "onboarding",
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


def test_arbitrary_lens_accepted(validator: Draft7Validator) -> None:
    """Any non-empty lens string is valid; enforcement of known lenses is at runtime."""
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "archive", "action": "edit", "page_hint": "specs/foo.md"}
        ],
    }
    validator.validate(doc)  # must NOT raise


def test_empty_lens_rejected(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [{"lens": "", "action": "edit", "page_hint": "ops/foo.md"}],
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
                "page_hint": "operations/foo.md",
                "extra": 1,
            }
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)


def test_doc_kind_decision_accepted(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "create",
                "page_hint": "architecture/foo.md",
                "doc_kind": "decision",
            }
        ],
    }
    validator.validate(doc)  # must NOT raise


def test_doc_kind_architecture_accepted(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "create",
                "page_hint": "architecture/foo.md",
                "doc_kind": "architecture",
            }
        ],
    }
    validator.validate(doc)


def test_doc_kind_invalid_value_rejected(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "create",
                "page_hint": "architecture/foo.md",
                "doc_kind": "ops",
            }
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)


def test_doc_kind_omitted_accepted(validator: Draft7Validator) -> None:
    # doc_kind is optional; omitting it validates (orchestrator defaults it to
    # "architecture" — the backward-compatible bare-host / legacy-output path).
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "core", "action": "create", "page_hint": "architecture/foo.md"}
        ],
    }
    validator.validate(doc)  # must NOT raise


# ---------- CCE-139: notes on a doc_targets item ----------


def test_doc_target_item_accepts_notes(validator: Draft7Validator) -> None:
    """Run #699 was rejected for emitting `notes` inside a doc_targets item. The
    root object already permitted notes; the item object did not."""
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "edit",
                "page_hint": "backend/api.md",
                "notes": "the endpoint moved; keep the old anchor",
            }
        ],
    }
    validator.validate(doc)


def test_doc_target_item_accepts_null_notes(validator: Draft7Validator) -> None:
    """Symmetric with the root-level notes, which is ["string", "null"]."""
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "core", "action": "edit", "page_hint": "a.md", "notes": None}
        ],
    }
    validator.validate(doc)


def test_doc_target_item_still_rejects_an_unknown_key(
    validator: Draft7Validator,
) -> None:
    """CONTROL: naming `notes` must not open the item shape. additionalProperties
    stays false, so a genuinely unknown key is still a contract violation."""
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "edit",
                "page_hint": "a.md",
                "confidence": 0.9,
            }
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import contracts_doc  # noqa: E402

SCHEMA = {
    "title": "Page Author Output",
    "description": "What the page-author subagent returns.",
    "type": "object",
    "required": ["page_path"],
    "properties": {
        "page_path": {"type": "string", "description": "Target path"},
        "status": {"type": "string", "enum": ["draft", "final"]},
        "lines": {"type": "array", "items": {"type": "integer"}},
    },
}


def test_type_str_handles_scalar_array_and_enum():
    assert contracts_doc._type_str({"type": "string"}) == "string"
    assert (
        contracts_doc._type_str({"type": "array", "items": {"type": "integer"}})
        == "array[integer]"
    )
    assert contracts_doc._type_str({"enum": ["a", "b"]}) == "enum"
    assert contracts_doc._type_str({"$ref": "#/$defs/Foo"}) == "Foo"


def test_render_contract_page_has_title_banner_and_table():
    page = contracts_doc.render_contract_page("page_author", SCHEMA)
    assert page.startswith("# Page Author Output")
    assert "Auto-generated" in page
    assert "What the page-author subagent returns." in page
    assert "| Property | Type | Required | Description |" in page
    assert "| `page_path` | string | yes | Target path |" in page
    assert "| `status` | enum | no |" in page


def test_render_falls_back_to_name_when_no_title():
    page = contracts_doc.render_contract_page("notifier", {"type": "object"})
    assert page.startswith("# notifier")
    assert "_No properties documented._" in page


def test_render_escapes_pipe_in_description():
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string", "description": "a | b"}},
    }
    page = contracts_doc.render_contract_page("x", schema)
    assert "a \\| b" in page


def test_type_str_handles_oneof_and_allof():
    assert (
        contracts_doc._type_str({"oneOf": [{"type": "string"}, {"type": "null"}]})
        == "string | null"
    )
    assert (
        contracts_doc._type_str(
            {"allOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}]}
        )
        == "A & B"
    )


def test_type_str_strips_newline_in_description():
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string", "description": "line1\nline2"}},
    }
    page = contracts_doc.render_contract_page("x", schema)
    assert "line1 line2" in page
    assert "line1\nline2" not in page


def test_render_index_sorted_and_linked():
    out = contracts_doc.render_index(["b", "a"])
    assert "- [a](a.md)" in out and "- [b](b.md)" in out
    assert out.index("[a](a.md)") < out.index("[b](b.md)")

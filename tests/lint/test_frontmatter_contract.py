from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import frontmatter_contract as fc  # noqa: E402


def test_required_fields_default_for_none_and_unknown():
    assert fc.required_fields(None) == ("status", "sources", "synthesized_into")
    assert fc.required_fields("changelog") == ("status", "sources", "synthesized_into")
    assert fc.required_fields("archive-index") == (
        "status",
        "sources",
        "synthesized_into",
    )


def test_required_fields_agent_authored():
    assert fc.required_fields("agent-authored") == (
        "description",
        "source_files",
        "last_reviewed",
        "status",
    )

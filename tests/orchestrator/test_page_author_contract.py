"""CCE-119 Item A / AC1: the page-author contract must require emitting the
lint-guarded agent-authored frontmatter fields verbatim for a create."""

from pathlib import Path

_CONTRACT = (
    Path(__file__).parent.parent.parent / "agents" / "page-author.md"
).read_text()


def test_contract_requires_verbatim_agent_authored_frontmatter():
    lowered = _CONTRACT.lower()
    assert "verbatim" in lowered, "contract must state the fields are emitted verbatim"
    # Anchor to the load-bearing AC1 instruction, not an incidental mention:
    # "do not reword" is unique to the agent-authored-create Procedure step, so
    # deleting that instruction must break this test (an unanchored token search
    # would still pass on the field-description sentence alone).
    assert "do not reword" in lowered, (
        "contract must forbid rewording the lint-guarded agent-authored fields"
    )
    assert "agent-authored create" in lowered
    assert "source_files" in _CONTRACT
    assert "last_reviewed" in _CONTRACT

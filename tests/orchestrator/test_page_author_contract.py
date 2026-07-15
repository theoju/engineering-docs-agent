"""CCE-119 Item A / AC1: the page-author contract must require emitting the
lint-guarded agent-authored frontmatter fields verbatim for a create."""

from pathlib import Path

_CONTRACT = (
    Path(__file__).parent.parent.parent / "agents" / "page-author.md"
).read_text()


def test_contract_requires_verbatim_agent_authored_frontmatter():
    lowered = _CONTRACT.lower()
    assert "verbatim" in lowered, "contract must state the fields are emitted verbatim"
    # anchored to the agent-authored create field set
    assert "source_files" in _CONTRACT
    assert "last_reviewed" in _CONTRACT

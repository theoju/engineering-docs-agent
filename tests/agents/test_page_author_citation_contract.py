"""CCE-122: the page-author contract must require line-free code citations
(`path` or `path:symbol`, never `path:line`)."""

from pathlib import Path

_CONTRACT = (
    Path(__file__).parent.parent.parent / "agents" / "page-author.md"
).read_text()


def test_contract_requires_line_free_citations():
    lowered = _CONTRACT.lower()
    assert "path:symbol" in lowered
    assert "never" in lowered and "path:line" in lowered
    # Anchor on the load-bearing phrase so deleting the rule breaks the test.
    assert "line-free" in lowered or "never cite a line number" in lowered

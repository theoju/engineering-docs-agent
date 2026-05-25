from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import archive_indexes  # noqa: E402


def test_parse_frontmatter_reads_status():
    text = "---\nstatus: accepted\n---\n\n# Foo\n"
    assert archive_indexes.parse_frontmatter(text).get("status") == "accepted"


def test_parse_frontmatter_absent_returns_empty():
    assert archive_indexes.parse_frontmatter("# No frontmatter\n") == {}


def test_parse_frontmatter_malformed_returns_empty():
    # Unparseable YAML in the block must degrade to {}, not raise.
    text = "---\nstatus: : :\n  - [bad\n---\n\n# Foo\n"
    assert archive_indexes.parse_frontmatter(text) == {}


def test_parse_title_and_summary():
    text = "---\nstatus: draft\n---\n\n# My Title\n\nFirst paragraph here.\n"
    title, summary = archive_indexes.parse_title_and_summary(text)
    assert title == "My Title"
    assert summary == "First paragraph here."


def test_parse_title_and_summary_skips_subheadings():
    text = "# Title\n\n## Section\n\nReal summary line.\n"
    title, summary = archive_indexes.parse_title_and_summary(text)
    assert title == "Title"
    assert summary == "Real summary line."


def test_parse_title_and_summary_no_h1_returns_empty():
    # No H1 -> ("", ""); collect_entries falls back to the filename for title.
    title, summary = archive_indexes.parse_title_and_summary("Prose.\nNo heading.\n")
    assert title == ""
    assert summary == ""


def test_parse_title_and_summary_title_without_body():
    title, summary = archive_indexes.parse_title_and_summary("# Only a title\n")
    assert title == "Only a title"
    assert summary == ""

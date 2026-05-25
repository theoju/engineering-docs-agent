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


_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "archive_indexes"


def test_collect_entries_filters_and_sorts():
    entries = archive_indexes.collect_entries(_FIXTURES / "specs", _FIXTURES)
    names = [e.filename for e in entries]
    # only date-prefixed .md, newest first; notes.md and the .txt are excluded
    assert names == [
        "2026-05-24-structured-docs-site.md",
        "2026-05-20-schema-enforcement.md",
    ]


def test_collect_entries_fields():
    entries = archive_indexes.collect_entries(_FIXTURES / "specs", _FIXTURES)
    by_name = {e.filename: e for e in entries}
    a = by_name["2026-05-24-structured-docs-site.md"]
    assert a.title == "Structured Docs Site"
    assert a.status == "draft"
    assert a.month == "2026-05"
    assert a.source_rel_path == "specs/2026-05-24-structured-docs-site.md"
    assert a.summary.startswith("Turn the agent")
    # no frontmatter status -> "—"
    assert by_name["2026-05-20-schema-enforcement.md"].status == "—"

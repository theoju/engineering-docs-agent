from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import archive_indexes  # noqa: E402


def _entry(
    filename, title="T", status="draft", summary="S", month="2026-05", rel="specs/x.md"
):
    return archive_indexes.Entry(filename, title, status, summary, month, rel)


def test_render_has_banner_and_month_headers():
    entries = [
        _entry("2026-05-24-a.md", month="2026-05", rel="specs/2026-05-24-a.md"),
        _entry("2026-04-01-b.md", month="2026-04", rel="specs/2026-04-01-b.md"),
    ]
    page = archive_indexes.render_archive_page("Specs", entries, link_base=None)
    assert "# Specs archive" in page
    assert "Auto-generated; 2 entries" in page
    assert "Do not edit by hand" in page
    # newest month first
    assert page.index("## 2026-05") < page.index("## 2026-04")
    assert "| Title | Status | Summary |" in page


def test_render_links_when_base_present():
    entries = [_entry("2026-05-24-a.md", title="Alpha", rel="specs/2026-05-24-a.md")]
    page = archive_indexes.render_archive_page(
        "Specs", entries, link_base="https://h/blob/main/"
    )
    assert "[Alpha](https://h/blob/main/specs/2026-05-24-a.md)" in page


def test_render_plain_when_no_base():
    entries = [_entry("2026-05-24-a.md", title="Alpha")]
    page = archive_indexes.render_archive_page("Specs", entries, link_base=None)
    assert "| Alpha |" in page
    assert "](" not in page  # no markdown links


def test_render_truncates_and_escapes():
    long = "x" * 200
    entries = [
        _entry("2026-05-24-a.md", title="A|B", status="d|e", summary=long + " | pipe")
    ]
    page = archive_indexes.render_archive_page("Specs", entries, link_base=None)
    assert "…" in page  # truncated
    assert "x" * 200 not in page  # not the full 200 chars
    assert "A\\|B" in page  # title pipe escaped
    assert "d\\|e" in page  # status pipe escaped


def test_render_escapes_pipe_within_summary():
    # a pipe inside the kept (non-truncated) summary must be escaped
    entries = [_entry("2026-05-24-a.md", summary="left | right")]
    page = archive_indexes.render_archive_page("Specs", entries, link_base=None)
    assert "left \\| right" in page


def test_render_normalizes_base_without_trailing_slash():
    entries = [_entry("2026-05-24-a.md", title="Alpha", rel="specs/a.md")]
    page = archive_indexes.render_archive_page(
        "Specs", entries, link_base="https://h/blob/main"
    )
    assert "[Alpha](https://h/blob/main/specs/a.md)" in page

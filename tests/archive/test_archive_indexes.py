from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import archive_indexes  # noqa: E402


def test_parse_frontmatter_strict_returns_dict_on_valid_input():
    text = "---\ndescription: hello world\nstatus: draft\n---\n# Body\n"
    fm = archive_indexes.parse_frontmatter_strict(text)
    assert fm == {"description": "hello world", "status": "draft"}


def test_parse_frontmatter_strict_returns_empty_dict_on_empty_block():
    text = "---\n---\n# Body\n"
    assert archive_indexes.parse_frontmatter_strict(text) == {}


def test_parse_frontmatter_strict_raises_yaml_error_on_bad_yaml():
    # The CCE-15-style failure: an unquoted YAML scalar containing ``: ``
    # (colon-space) is parsed as a nested mapping separator. Backticks are
    # incidental — pyyaml does not treat them specially; the bare ``: ``
    # inside the value is what triggers the parser to choke.
    text = "---\ndescription: `additionalProperties: false`\n---\n"
    with pytest.raises(yaml.YAMLError):
        archive_indexes.parse_frontmatter_strict(text)


def test_parse_frontmatter_strict_raises_value_error_on_no_frontmatter():
    with pytest.raises(ValueError, match="no opening fence"):
        archive_indexes.parse_frontmatter_strict("# No frontmatter here\n")
    # And on truncated frontmatter (missing closing fence).
    with pytest.raises(ValueError, match="no closing fence"):
        archive_indexes.parse_frontmatter_strict("---\ndescription: x\n# Body\n")


def test_parse_frontmatter_strict_raises_value_error_on_non_mapping():
    # A YAML list at the top level parses successfully but is not a dict —
    # the strict parser surfaces this rather than coercing to {} so callers
    # can distinguish it from an empty frontmatter block.
    with pytest.raises(ValueError, match="not a mapping"):
        archive_indexes.parse_frontmatter_strict("---\n- one\n- two\n---\n")


def test_render_strips_inline_links_from_summary():
    """CCE-104: a source summary containing a relative markdown link must not
    leak that link into the archive table — mkdocs --strict resolves it against
    the archive/ dir and aborts. Keep the link TEXT, drop the target."""
    entry = archive_indexes.Entry(
        filename="2026-05-21-x.md",
        title="X",
        status="draft",
        summary="see [baseline](2026-05-21-cce16-real-baseline.md) for the numbers",
        month="2026-05",
        source_rel_path="docs/superpowers/measurements/2026-05-21-x.md",
    )
    out = archive_indexes.render_archive_page("Measurements", [entry], link_base=None)
    assert "2026-05-21-cce16-real-baseline.md" not in out  # no broken relative link
    assert "baseline" in out  # link text preserved as plain text


def test_render_strips_inline_links_from_title():
    """A title carrying a markdown link would break the wrapping [title](src) link;
    strip it to plain text so the Title cell stays a single valid link."""
    entry = archive_indexes.Entry(
        filename="2026-05-21-y.md",
        title="Adopt [thing](other.md) now",
        status="draft",
        summary="ok",
        month="2026-05",
        source_rel_path="docs/superpowers/specs/2026-05-21-y.md",
    )
    out = archive_indexes.render_archive_page(
        "Specs", [entry], link_base="https://h/blob/main/"
    )
    assert "other.md" not in out
    assert "Adopt thing now" in out

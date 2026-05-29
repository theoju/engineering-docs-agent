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

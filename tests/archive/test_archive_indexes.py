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
    # The CCE-15-style failure: a bare `: ` inside a backticked value
    # makes pyyaml treat it as a nested mapping separator.
    text = "---\ndescription: `additionalProperties: false`\n---\n"
    with pytest.raises(yaml.YAMLError):
        archive_indexes.parse_frontmatter_strict(text)


def test_parse_frontmatter_strict_raises_value_error_on_no_frontmatter():
    with pytest.raises(ValueError):
        archive_indexes.parse_frontmatter_strict("# No frontmatter here\n")
    # And on truncated frontmatter (missing closing fence).
    with pytest.raises(ValueError):
        archive_indexes.parse_frontmatter_strict("---\ndescription: x\n# Body\n")

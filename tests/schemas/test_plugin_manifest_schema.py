"""CCE-16: enforce .claude-plugin/plugin.json matches the Claude Code
plugin-loader's required manifest shape. The actual schema lives in the
Claude CLI's Zod validator; ours is a local minimum that catches the
class of bug that silently broke all subagent loading for two days
(CCE-12 through CCE-15 baselines all measured default Claude Code
instead of the real agents because the manifest's `author` field was
a string, not an object)."""

from __future__ import annotations
import json
from pathlib import Path
from jsonschema import validate, ValidationError
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SCHEMA = json.loads(
    (REPO_ROOT / "templates" / "plugin_manifest.schema.json").read_text()
)
MANIFEST = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())


def test_actual_manifest_matches_schema():
    """The live plugin.json must validate. Catches the CCE-16
    'author as string' regression and any analogous shape break."""
    validate(MANIFEST, SCHEMA)


def test_author_string_is_rejected():
    """Regression guard: the exact bug shape that broke us for two
    days (author as a bare string) must fail validation."""
    broken = {**MANIFEST, "author": "Theo Jungeblut"}
    with pytest.raises(ValidationError, match="author"):
        validate(broken, SCHEMA)


def test_author_object_without_name_is_rejected():
    """Author must have at least a name property — the CLI validator
    requires it."""
    broken = {**MANIFEST, "author": {"email": "x@y.z"}}
    with pytest.raises(ValidationError, match="name"):
        validate(broken, SCHEMA)


def test_missing_required_field_rejected():
    """Required fields: name, version, description, author."""
    for missing in ("name", "version", "description", "author"):
        broken = {k: v for k, v in MANIFEST.items() if k != missing}
        with pytest.raises(ValidationError):
            validate(broken, SCHEMA)


def test_extra_top_level_field_allowed():
    """additionalProperties:true at the root — homepage, repository,
    keywords, etc. should not cause rejection."""
    extended = {**MANIFEST, "homepage": "https://example.com"}
    validate(extended, SCHEMA)

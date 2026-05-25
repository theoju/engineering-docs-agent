"""CCE-23: the shipped default site template is valid and is Candidate A."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import validate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = json.loads((_REPO_ROOT / "templates" / "config.schema.json").read_text())


def test_default_template_matches_schema_and_candidate_a():
    site = yaml.safe_load((_REPO_ROOT / "templates" / "site.default.yaml").read_text())
    validate(site, _SCHEMA["properties"]["site"])
    keys = [s["key"] for s in site["sections"]]
    assert keys == ["home", "architecture", "api", "operations", "archive", "whats-new"]
    assert site["docs_dir"] == "docs/site-src"
    assert site["theme"] == "material"

from __future__ import annotations
import json
import yaml
from pathlib import Path
from jsonschema import validate, ValidationError
import pytest

SCHEMA = json.loads(
    (
        Path(__file__).parent.parent.parent / "templates" / "config.schema.json"
    ).read_text()
)


def test_minimal_valid():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/core }
sources: { git: { host: github } }
lint: { tier1: default, tier2: {}, tier3: {} }
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
notifications: {}
""")
    validate(cfg, SCHEMA)


def test_missing_required_docs_field_rejected():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
sources: { git: { host: github } }
lint: {}
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
notifications: {}
""")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_invalid_framework_rejected():
    cfg = yaml.safe_load("""
docs:
  framework: jekyll
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
notifications: {}
""")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)

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


def test_site_block_valid():
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
site:
  docs_dir: docs/site-src
  theme: material
  sections:
    - { key: home, path: index.md, title: Home }
    - { key: api, path: api/, title: API reference, generator: api-extract }
""")
    validate(cfg, SCHEMA)


def test_site_section_requires_key_path_title():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: https://x, build_workflow: deploy.yml, url_map_rule: standard }
notifications: {}
site:
  docs_dir: docs/site-src
  sections:
    - { key: home }
""")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_site_unknown_generator_rejected():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: https://x, build_workflow: deploy.yml, url_map_rule: standard }
notifications: {}
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: not-a-generator }
""")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_site_empty_docs_dir_rejected():
    # An empty docs_dir would make the path-containment guard pass everything;
    # the schema's minLength closes that at load time.
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: https://x, build_workflow: deploy.yml, url_map_rule: standard }
notifications: {}
site:
  docs_dir: ""
  sections:
    - { key: home, path: index.md, title: Home }
""")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_config_without_site_block_still_valid():
    # Backward compatibility: site is optional.
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/core }
sources: { git: { host: github } }
lint: {}
publishing: { base_url: https://x, build_workflow: deploy.yml, url_map_rule: standard }
notifications: {}
""")
    validate(cfg, SCHEMA)


def test_site_section_repo_url_base_allowed():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: https://x, build_workflow: deploy.yml, url_map_rule: standard }
notifications: {}
site:
  docs_dir: docs/site-src
  sections:
    - { key: archive, path: archive/, title: Archive, generator: archive-index,
        sources: [docs/superpowers/specs], repo_url_base: https://h/blob/main/ }
""")
    validate(cfg, SCHEMA)


# CCE-58: publishing.ci_provider is an additive enum so host configs can
# declare which CI provider runs the docs publish workflow. Only `github`
# is wired through scripts/verify_runner.py today; `circleci` is reserved
# for a follow-up sub-ticket. Configs without the field stay valid
# (default behavior preserved).
def test_publishing_ci_provider_accepts_github():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/ }
sources: { git: { host: github } }
lint: {}
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
  ci_provider: github
notifications: {}
""")
    validate(cfg, SCHEMA)


def test_publishing_ci_provider_accepts_circleci():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/ }
sources: { git: { host: github } }
lint: {}
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
  ci_provider: circleci
notifications: {}
""")
    validate(cfg, SCHEMA)


def test_publishing_ci_provider_rejects_unknown():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/ }
sources: { git: { host: github } }
lint: {}
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
  ci_provider: gitlab
notifications: {}
""")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_framework_none_accepted():
    cfg = yaml.safe_load("""
docs:
  framework: none
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/ }
sources: { git: { host: github } }
lint: { tier1: default }
publishing:
  base_url: null
  build_workflow: null
  url_map_rule: standard
notifications: {}
""")
    validate(cfg, SCHEMA)


def test_framework_hugo_rejected():
    cfg = yaml.safe_load("""
docs:
  framework: hugo
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

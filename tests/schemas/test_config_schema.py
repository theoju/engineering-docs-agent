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


_BASE_FOR_MERGE = """
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
"""


def test_merge_block_valid():
    cfg = yaml.safe_load(
        _BASE_FOR_MERGE
        + """
merge:
  policy: auto
  checks_grace_seconds: 120
  checks_timeout_seconds: 900
"""
    )
    validate(cfg, SCHEMA)


def test_merge_policy_manual_valid():
    cfg = yaml.safe_load(_BASE_FOR_MERGE + "\nmerge: { policy: manual }\n")
    validate(cfg, SCHEMA)


def test_merge_block_absent_valid():
    """CCE-101: merge is optional — absent block means policy auto."""
    cfg = yaml.safe_load(_BASE_FOR_MERGE)
    validate(cfg, SCHEMA)


def test_merge_unknown_policy_rejected():
    cfg = yaml.safe_load(_BASE_FOR_MERGE + "\nmerge: { policy: rebase }\n")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_merge_unknown_key_rejected():
    cfg = yaml.safe_load(_BASE_FOR_MERGE + "\nmerge: { method: squash }\n")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_merge_negative_grace_rejected():
    cfg = yaml.safe_load(_BASE_FOR_MERGE + "\nmerge: { checks_grace_seconds: -1 }\n")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


# ---------- CCE-139: lint.citation_source_roots ----------

_BASE_CFG = """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/core }
sources: { git: { host: github } }
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
notifications: {}
"""


def test_citation_source_roots_package_roots_accepted():
    cfg = yaml.safe_load(
        _BASE_CFG
        + "lint: { tier1: default, citation_source_roots: [backend, frontend] }\n"
    )
    validate(cfg, SCHEMA)


def test_citation_source_roots_rejects_a_nested_tail():
    """Spec: roots must be PACKAGE roots, never a tail like `backend/storage`.
    A root list deep enough to catch tails is suffix-matching in disguise."""
    cfg = yaml.safe_load(
        _BASE_CFG
        + "lint: { tier1: default, citation_source_roots: [backend/storage] }\n"
    )
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_citation_source_roots_rejects_a_bare_string():
    """The value is a list of roots, not one root. An undeclared key would have
    accepted this silently."""
    cfg = yaml.safe_load(
        _BASE_CFG + 'lint: { tier1: default, citation_source_roots: "backend" }\n'
    )
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


# ---------------------------------------------------------------------------
# CCE-140: run.deferral_skip_threshold
# ---------------------------------------------------------------------------

_CCE140_BASE_CFG = """
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
"""


def test_run_block_accepts_deferral_skip_threshold():
    """CCE-140: the `run` block sets additionalProperties: false, so an
    undeclared key makes load_config_validated raise and the runner exit 2.
    The schema edit is a hard requirement, not documentation."""
    cfg = yaml.safe_load(_CCE140_BASE_CFG)
    cfg["run"] = {"time_budget_seconds": 2700, "deferral_skip_threshold": 3}
    validate(cfg, SCHEMA)


def test_run_block_still_rejects_an_unknown_key():
    cfg = yaml.safe_load(_CCE140_BASE_CFG)
    cfg["run"] = {"deferral_skip_threshhold": 3}  # typo, one 'h' too many
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_run_block_accepts_authoring_hard_cap_seconds():
    """CCE-152: the key was documented in the resolver's docstring and read by
    `resolve_authoring_hard_cap` while the schema still rejected it, so a host
    that followed the documentation aborted its nightly at config validation
    with exit 2. The `integer` type also guards the resolver's `int(val)`,
    which was otherwise unguarded against `authoring_hard_cap_seconds: soon`."""
    cfg = yaml.safe_load(_CCE140_BASE_CFG)
    cfg["run"] = {"time_budget_seconds": 2100, "authoring_hard_cap_seconds": 2415}
    validate(cfg, SCHEMA)


@pytest.mark.parametrize("bad", [0, -1, "soon", 2415.5])
def test_authoring_hard_cap_seconds_rejects_a_non_positive_integer(bad):
    cfg = yaml.safe_load(_CCE140_BASE_CFG)
    cfg["run"] = {"authoring_hard_cap_seconds": bad}
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_deferral_skip_threshold_rejects_a_negative():
    cfg = yaml.safe_load(_CCE140_BASE_CFG)
    cfg["run"] = {"deferral_skip_threshold": -1}
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)

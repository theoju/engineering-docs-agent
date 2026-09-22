"""CCE-181: an invalid external_repos declaration must stop the run at load.

The collision guard needs the repo tree. load_config_validated takes only the config
path -- but that path is <repo>/.engineering-docs-agent/config.yml, so the repo
root is path.parent.parent. Deriving it there keeps the guard at load time, as
the spec requires, without changing load_config_validated's signature.
"""

import pytest
import yaml

from scripts.state_io import ConfigError, load_config_validated

# BASE carries the schema-required keys outside of `lint` (docs.whats_new_file,
# sources, publishing, notifications) so each fixture below exercises only the
# external_repos validation, never an unrelated "is a required property" error.
# Same pattern as tests/state_io/test_config_validation_lens_editable.py's
# _SCHEMA_TAIL.
BASE = {
    "docs": {
        "framework": "mkdocs",
        "source_dir": "docs",
        "whats_new_file": "docs/whats-new.md",
        "agent_editable_paths": ["docs/**"],
        "lens_paths": {"core": "docs/"},
    },
    "sources": {"git": {"host": "github.com"}},
    "publishing": {
        "base_url": "https://example.com",
        "build_workflow": "ci.yml",
        "url_map_rule": "strip-ext",
    },
    "notifications": {},
}


def _write(tmp_path, lint):
    repo = tmp_path
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    cfg_dir = repo / ".engineering-docs-agent"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg_dir / "config.yml"
    cfg.write_text(yaml.safe_dump({**BASE, "lint": lint}))
    return cfg


def test_a_valid_declaration_loads(tmp_path):
    cfg = _write(tmp_path, {"external_repos": {"eda": {"url": "https://x.example/r"}}})
    loaded = load_config_validated(cfg)
    assert loaded["lint"]["external_repos"]["eda"]["url"] == "https://x.example/r"


def test_both_url_and_private_is_refused_at_load(tmp_path):
    cfg = _write(
        tmp_path,
        {"external_repos": {"eda": {"url": "https://x.example/r", "private": True}}},
    )
    with pytest.raises(ConfigError):
        load_config_validated(cfg)


def test_a_prefix_colliding_with_a_real_repo_directory_is_refused(tmp_path):
    """`docs/` exists in the fixture repo, so declaring `docs` as external
    would rewrite real local paths into foreign links."""
    cfg = _write(tmp_path, {"external_repos": {"docs": {"url": "https://x.example/r"}}})
    with pytest.raises(ConfigError, match="collides"):
        load_config_validated(cfg)

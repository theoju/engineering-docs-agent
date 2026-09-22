"""CCE-181: an invalid external_repos declaration must stop the run at load.

The collision guard needs the repo tree. load_config_validated takes only the config
path -- but that path is <repo>/.engineering-docs-agent/config.yml, so the repo
root is path.parent.parent. Deriving it there keeps the guard at load time, as
the spec requires, without changing load_config_validated's signature.
"""

from pathlib import Path

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


def test_absent_external_repos_does_no_filesystem_listing(tmp_path, monkeypatch):
    """A host that never declares lint.external_repos must not pay for the
    collision guard's repo-tree listing at all -- not just get a no-op result
    after listing. Path.iterdir is monkeypatched to blow up; a clean load
    proves _repo_root.iterdir() was never reached. The block-present case is
    the contrasting proof: the same monkeypatch surfaces the attempted call,
    showing the guard's I/O is conditional on the feature being declared,
    not skipped altogether.
    """

    def _boom(self):
        raise OSError("iterdir must not run when lint.external_repos is absent")

    monkeypatch.setattr(Path, "iterdir", _boom)

    cfg = _write(tmp_path, {})
    loaded = load_config_validated(cfg)
    assert "external_repos" not in (loaded.get("lint") or {})

    cfg2 = _write(tmp_path, {"external_repos": {"eda": {"url": "https://x.example/r"}}})
    with pytest.raises(OSError):
        load_config_validated(cfg2)

from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

VALID_CFG = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/core }
sources:
  git: { host: github }
lint: { tier1: default }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
notifications: {}
"""


def test_load_config_validated_accepts_valid(tmp_path):
    from state_io import load_config_validated

    p = tmp_path / "config.yml"
    p.write_text(VALID_CFG)
    cfg = load_config_validated(p)
    assert cfg["docs"]["framework"] == "mkdocs"


def test_load_config_validated_rejects_missing_required(tmp_path):
    from state_io import load_config_validated, ConfigError

    p = tmp_path / "config.yml"
    p.write_text("docs:\n  framework: mkdocs\n")
    with pytest.raises(ConfigError):
        load_config_validated(p)


def test_load_config_validated_rejects_bad_enum(tmp_path):
    from state_io import load_config_validated, ConfigError

    bad = VALID_CFG.replace("framework: mkdocs", "framework: vuepress")
    p = tmp_path / "config.yml"
    p.write_text(bad)
    with pytest.raises(ConfigError):
        load_config_validated(p)


def test_load_config_validated_missing_file(tmp_path):
    from state_io import load_config_validated, ConfigError

    with pytest.raises(ConfigError):
        load_config_validated(tmp_path / "nope.yml")

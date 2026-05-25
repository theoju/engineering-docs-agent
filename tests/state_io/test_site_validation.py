"""CCE-23: load_config_validated rejects internally-inconsistent site: blocks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from state_io import ConfigError, load_config_validated  # noqa: E402

_TAIL = """
sources:
  git: { host: github.com }
lint: {}
publishing:
  base_url: "https://example.com"
  build_workflow: "ci.yml"
  url_map_rule: "strip-ext"
notifications: {}
"""

_DOCS = """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths: {}
"""


def _write(tmp_path: Path, site_body: str) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(_DOCS + site_body + _TAIL)
    return p


def test_valid_site_passes(tmp_path: Path):
    cfg = load_config_validated(
        _write(
            tmp_path,
            """
site:
  docs_dir: docs/site-src
  sections:
    - { key: home, path: index.md, title: Home }
    - { key: api, path: api/, title: API reference, generator: api-extract,
        extractors: [python-mkdocstrings] }
""",
        )
    )
    assert cfg["site"]["sections"][0]["key"] == "home"


def test_duplicate_section_key_raises(tmp_path: Path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API }
    - { key: api, path: api2/, title: API 2 }
""",
            )
        )
    assert "duplicate" in str(exc.value).lower() and "api" in str(exc.value)


def test_section_path_outside_docs_dir_raises(tmp_path: Path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - { key: home, path: ../escape.md, title: Home }
""",
            )
        )
    assert "docs_dir" in str(exc.value) or "outside" in str(exc.value)


def test_section_absolute_path_raises(tmp_path: Path):
    # An absolute path joins to escape docs_dir; the startswith guard rejects it.
    with pytest.raises(ConfigError) as exc:
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - { key: home, path: /etc/passwd, title: Home }
""",
            )
        )
    assert "docs_dir" in str(exc.value) or "outside" in str(exc.value)


def test_no_site_block_is_fine(tmp_path: Path):
    cfg = load_config_validated(_write(tmp_path, ""))
    assert "site" not in cfg

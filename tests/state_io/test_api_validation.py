from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from state_io import ConfigError, load_config_validated  # noqa: E402

_DOCS = """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths: {}
"""
_TAIL = """
sources: { git: { host: github.com } }
lint: {}
publishing: { base_url: "https://x", build_workflow: "ci.yml", url_map_rule: "strip-ext" }
notifications: {}
"""


def _write(tmp_path: Path, site_body: str) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(_DOCS + site_body + _TAIL)
    return p


def test_api_extract_requires_extractors(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: api-extract }
""",
            )
        )
    assert "extractors" in str(exc.value)


def test_openapi_extractor_requires_openapi_path(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: api-extract,
        extractors: [openapi] }
""",
            )
        )
    assert "openapi" in str(exc.value).lower()


def test_openapi_path_must_be_repo_relative(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: api-extract,
        extractors: [openapi], openapi: /etc/openapi.json }
""",
            )
        )
    assert "relative" in str(exc.value).lower() or "absolute" in str(exc.value).lower()


def test_api_extract_rejects_unsafe_sources(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: api-extract,
        extractors: [json-schema], sources: ["../../etc"] }
""",
            )
        )
    assert "relative" in str(exc.value).lower() or "absolute" in str(exc.value).lower()


def test_valid_api_extract_passes(tmp_path):
    cfg = load_config_validated(
        _write(
            tmp_path,
            """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: api-extract,
        extractors: [python-mkdocstrings, json-schema, openapi],
        sources: [agents/schemas], openapi: openapi.json }
""",
        )
    )
    assert cfg["site"]["sections"][0]["openapi"] == "openapi.json"


def test_openapi_path_rejects_traversal(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: api-extract,
        extractors: [openapi], openapi: "sub/../../etc/passwd" }
""",
            )
        )
    assert "relative" in str(exc.value).lower() or "absolute" in str(exc.value).lower()
